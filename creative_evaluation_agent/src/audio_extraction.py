"""video -> local audio extraction -> API-supported format (spec: user request 2026-09-12).

Uses imageio-ffmpeg's bundled ffmpeg binary (no system ffmpeg install required — same
no-external-dependency principle as frame_extractor.py's opencv-only approach). Extracted
audio is written to cache/audio_staging/ and never touches the original video file.

Why this fixes the .mov / 25MB problems at the root:
- Whisper only accepts specific containers (mp4/mp3/wav/webm/...), not .mov — extracting to
  mp3 sidesteps container support entirely, regardless of the source video's format.
- The 25MB limit was being applied to the whole video (video+audio); a short ad clip's
  audio track alone, re-encoded as mono 16kHz/64kbps speech-quality mp3, is typically two
  orders of magnitude smaller than the source file, so it clears the limit in practice.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUDIO_STAGING_DIR = PROJECT_ROOT / "cache" / "audio_staging"

# Whisper API 공식 지원 포맷: flac, m4a, mp3, mp4, mpeg, mpga, oga, ogg, wav, webm.
# mp3로 통일 추출 — 음성 전용이라 저비트레이트로도 충분하고 용량이 가장 작다.
AUDIO_SAMPLE_RATE_HZ = 16000
AUDIO_BITRATE = "64k"
AUDIO_CHANNELS = 1

STATUS_OK = "OK"
STATUS_NO_AUDIO_STREAM = "NO_AUDIO_STREAM"
STATUS_FFMPEG_ERROR = "FFMPEG_ERROR"

# 빈/무음 트랙만 뽑혔을 때의 최소 유효 크기 (그보다 작으면 사실상 오디오 없음으로 간주)
MIN_VALID_AUDIO_BYTES = 200


@dataclass
class AudioExtractionResult:
    status: str  # OK | NO_AUDIO_STREAM | FFMPEG_ERROR
    audio_path: Path | None
    size_bytes: int | None
    error_detail: str | None = None


def _staged_audio_path(video_hash: str) -> Path:
    return AUDIO_STAGING_DIR / f"{video_hash}.mp3"


def extract_audio(video_path: Path, video_hash: str) -> AudioExtractionResult:
    """Idempotent: reuses the staged file if it already exists for this video's content hash."""
    AUDIO_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _staged_audio_path(video_hash)

    if out_path.exists() and out_path.stat().st_size >= MIN_VALID_AUDIO_BYTES:
        return AudioExtractionResult(status=STATUS_OK, audio_path=out_path, size_bytes=out_path.stat().st_size)

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg_exe, "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "libmp3lame",
        "-ar", str(AUDIO_SAMPLE_RATE_HZ),
        "-ac", str(AUDIO_CHANNELS),
        "-b:a", AUDIO_BITRATE,
        str(out_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired as e:
        return AudioExtractionResult(status=STATUS_FFMPEG_ERROR, audio_path=None, size_bytes=None, error_detail=str(e))
    except Exception as e:  # noqa: BLE001 - must never crash the caller
        return AudioExtractionResult(status=STATUS_FFMPEG_ERROR, audio_path=None, size_bytes=None, error_detail=str(e))

    stderr_lower = (result.stderr or "").lower()
    no_audio_markers = ["does not contain any stream", "stream map '0:a' matches no streams", "output file is empty"]

    if result.returncode != 0:
        if any(marker in stderr_lower for marker in no_audio_markers):
            if out_path.exists():
                out_path.unlink()
            return AudioExtractionResult(status=STATUS_NO_AUDIO_STREAM, audio_path=None, size_bytes=None,
                                          error_detail="영상에 오디오 트랙이 없음")
        return AudioExtractionResult(status=STATUS_FFMPEG_ERROR, audio_path=None, size_bytes=None,
                                      error_detail=result.stderr[-1000:] if result.stderr else "unknown ffmpeg error")

    if not out_path.exists() or out_path.stat().st_size < MIN_VALID_AUDIO_BYTES:
        if out_path.exists():
            out_path.unlink()
        return AudioExtractionResult(status=STATUS_NO_AUDIO_STREAM, audio_path=None, size_bytes=None,
                                      error_detail="추출된 오디오가 사실상 비어있음 (무음/오디오 트랙 없음으로 판단)")

    return AudioExtractionResult(status=STATUS_OK, audio_path=out_path, size_bytes=out_path.stat().st_size)
