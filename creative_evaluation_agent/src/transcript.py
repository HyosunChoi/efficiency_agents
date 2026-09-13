"""Provider-neutral transcript generation: video -> local audio extraction -> validated
audio -> Whisper (spec §6/§15; redesigned 2026-09-12 — see src/audio_extraction.py).

Transcript success no longer depends on the source video's container format or overall
file size: audio is extracted locally first (never touching the original video), and the
25MB size / format checks apply to the extracted audio, not the raw video.

Always uses the same STT regardless of which vision provider (OpenAI/Claude) analyzes the
creative, so both providers see identical text input ("Provider 간 입력조건 동일 유지").
Requires OPENAI_API_KEY even when benchmarking Claude vision.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from src.audio_extraction import extract_audio
from src.config_loader import get_model_config

logger = logging.getLogger(__name__)

# transcript 캐시 키에 반영된다 — 파이프라인이 바뀌면(예: 이번 오디오 추출 도입) 이전 파이프라인
# 캐시를 자동으로 재사용하지 않는다. 레거시로 이미 성공한 transcript를 그대로 들고 오려면
# src/transcript_migration.py가 이 새 키로 명시적으로 이관(migrate)한다.
PIPELINE_VERSION = "v2_audio_extraction"

STATUS_OK = "OK"
STATUS_NA = "N/A"
STATUS_TOO_LARGE = "TRANSCRIPT_UNAVAILABLE_TOO_LARGE"
STATUS_NO_AUDIO_STREAM = "NO_AUDIO_STREAM"
STATUS_API_ERROR = "API_ERROR"

# 결정적 실패(같은 파일이면 재시도해도 같은 결과) -> 캐시해서 매번 ffmpeg를 다시 돌리지 않는다.
# 일시적 실패(API_ERROR, ffmpeg 프로세스 실패)는 캐시하지 않아 다음 실행에서 재시도된다.
_DETERMINISTIC_FAILURE_STATUSES = {STATUS_TOO_LARGE, STATUS_NO_AUDIO_STREAM}


@dataclass
class TranscriptResult:
    text: str | None
    status: str
    char_count: int = 0
    source: str = ""  # 예: "whisper-1"
    transcript_hash: str = ""  # sha256(text); 텍스트 없으면 ""
    error_code: str | None = None
    audio_extraction_status: str = "N/A"  # OK | NO_AUDIO_STREAM | FFMPEG_ERROR | N/A


def hash_text(text: str | None) -> str:
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def transcript_cache_key_for(video_hash: str, whisper_model: str) -> str:
    from src.cache import build_transcript_cache_key

    return build_transcript_cache_key(f"{video_hash}|{PIPELINE_VERSION}", whisper_model)


def _to_result(cached: dict) -> TranscriptResult:
    return TranscriptResult(
        text=cached.get("text"),
        status=cached["status"],
        char_count=cached.get("char_count", 0),
        source=cached.get("source", ""),
        transcript_hash=cached.get("transcript_hash", ""),
        error_code=cached.get("error_code"),
        audio_extraction_status=cached.get("audio_extraction_status", "N/A"),
    )


def _to_cache_dict(result: TranscriptResult) -> dict:
    return {
        "text": result.text,
        "status": result.status,
        "char_count": result.char_count,
        "source": result.source,
        "transcript_hash": result.transcript_hash,
        "error_code": result.error_code,
        "audio_extraction_status": result.audio_extraction_status,
    }


def predict_transcript_outcome(video_path: Path, video_hash: str) -> tuple[str, str]:
    """Local-only (no Whisper call) prediction of what get_transcript() would produce for a
    video that hasn't gone through the current pipeline yet. Runs real audio extraction
    (free/local — see audio_extraction.py) to answer "would this pass the size/format
    checks", without ever calling the paid transcription API. Returns (predicted_status,
    detail) where predicted_status is one of: PREDICTED_OK / TOO_LARGE / NO_AUDIO_STREAM /
    FFMPEG_ERROR. Used by cost_estimator.py and transcript_migration.py so a dry-run can
    report an accurate expected outcome before anyone approves a real API call.
    """
    cfg = get_model_config()["transcript"]
    max_size_bytes = cfg["max_file_size_mb"] * 1024 * 1024

    extraction = extract_audio(video_path, video_hash)
    if extraction.status == "NO_AUDIO_STREAM":
        return "NO_AUDIO_STREAM", extraction.error_detail or "오디오 트랙 없음"
    if extraction.status == "FFMPEG_ERROR":
        return "FFMPEG_ERROR", extraction.error_detail or "오디오 추출 실패 (일시적일 수 있음)"
    if extraction.size_bytes > max_size_bytes:
        return "TOO_LARGE", f"추출된 오디오가 {extraction.size_bytes/1024/1024:.1f}MB로 한도({cfg['max_file_size_mb']}MB) 초과"
    return "PREDICTED_OK", f"추출된 오디오 {extraction.size_bytes/1024:.0f}KB, mp3 포맷 — Whisper 호출 시 성공 예상"


def peek_cached_transcript(video_path: Path) -> TranscriptResult | None:
    """Read-only: returns the cached transcript for this video under the CURRENT pipeline
    version if one exists, without ever calling extract_audio() or Whisper. Used by cost
    estimation / migration planning, which must never trigger a paid call or even a local
    ffmpeg run just to check "do we already know the answer".
    """
    from src.cache import get_cached_transcript, hash_file

    cfg = get_model_config()["transcript"]
    video_hash = hash_file(video_path)
    cache_key = transcript_cache_key_for(video_hash, cfg["model"])
    cached = get_cached_transcript(cache_key)
    return _to_result(cached) if cached is not None else None


def get_transcript(video_path: Path) -> TranscriptResult:
    from src.cache import get_cached_transcript, hash_file, save_cached_transcript

    cfg = get_model_config()["transcript"]
    max_size_bytes = cfg["max_file_size_mb"] * 1024 * 1024
    whisper_model = cfg["model"]

    video_hash = hash_file(video_path)
    cache_key = transcript_cache_key_for(video_hash, whisper_model)
    cached = get_cached_transcript(cache_key)
    if cached is not None:
        logger.info("CACHE_HIT (transcript): %s", video_path.name)
        return _to_result(cached)

    extraction = extract_audio(video_path, video_hash)

    if extraction.status == "NO_AUDIO_STREAM":
        logger.warning("%s: 오디오 트랙이 없어 transcript 생략", video_path.name)
        result = TranscriptResult(
            text=None, status=STATUS_NO_AUDIO_STREAM, error_code="NO_AUDIO_STREAM",
            audio_extraction_status=extraction.status,
        )
        save_cached_transcript(cache_key, _to_cache_dict(result))
        return result

    if extraction.status == "FFMPEG_ERROR":
        logger.error("%s: 오디오 추출 실패 — %s", video_path.name, extraction.error_detail)
        return TranscriptResult(
            text=None, status=STATUS_API_ERROR, error_code="AUDIO_EXTRACTION_FAILED",
            audio_extraction_status=extraction.status,
        )  # 일시적일 수 있어 캐시하지 않음 (다음 실행에서 재시도)

    audio_path = extraction.audio_path
    if extraction.size_bytes > max_size_bytes:
        logger.warning(
            "%s: 추출된 오디오 크기(%.1fMB)가 한도(%dMB) 초과 — transcript 생략 (임의 압축/추정 안 함)",
            video_path.name, extraction.size_bytes / 1024 / 1024, cfg["max_file_size_mb"],
        )
        result = TranscriptResult(
            text=None, status=STATUS_TOO_LARGE, error_code="AUDIO_TOO_LARGE",
            audio_extraction_status=extraction.status,
        )
        save_cached_transcript(cache_key, _to_cache_dict(result))
        return result

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY가 설정되지 않아 transcript를 생성할 수 없습니다.")
        return TranscriptResult(
            text=None, status=STATUS_API_ERROR, error_code="NO_API_KEY",
            audio_extraction_status=extraction.status,
        )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        with open(audio_path, "rb") as f:
            response = client.audio.transcriptions.create(model=whisper_model, file=f)
        text = response.text
        result = TranscriptResult(
            text=text,
            status=STATUS_OK,
            char_count=len(text or ""),
            source=whisper_model,
            transcript_hash=hash_text(text),
            audio_extraction_status=extraction.status,
        )
    except Exception as e:  # noqa: BLE001 - provider/network errors must not crash the run
        logger.error("Whisper transcription 실패 (%s): %s", video_path.name, e)
        error_code = "UNSUPPORTED_FORMAT" if "invalid file format" in str(e).lower() else "WHISPER_API_ERROR"
        return TranscriptResult(
            text=None, status=STATUS_API_ERROR, error_code=error_code,
            audio_extraction_status=extraction.status,
        )  # API 오류는 캐시하지 않음 (다음 실행에서 재시도)

    save_cached_transcript(cache_key, _to_cache_dict(result))
    return result
