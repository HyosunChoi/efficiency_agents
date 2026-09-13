"""Analysis cache: file hash + provider/model + prompt/schema version (spec §8).

Same asset + same provider/model/prompt/schema -> reuse cached result, no new API call.
Also memoizes per-file content hashes (cache/asset_hashes) so re-hashing large video files
on every run isn't necessary.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.providers.base import CreativeAnalysisResult

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSET_HASH_CACHE_DIR = PROJECT_ROOT / "cache" / "asset_hashes"
ANALYSIS_CACHE_DIR = PROJECT_ROOT / "cache" / "creative_analysis"
TRANSCRIPT_CACHE_DIR = PROJECT_ROOT / "cache" / "creative_analysis" / "transcripts"
ASSET_HASH_INDEX = ASSET_HASH_CACHE_DIR / "index.json"


def _load_asset_hash_index() -> dict:
    if not ASSET_HASH_INDEX.exists():
        return {}
    with open(ASSET_HASH_INDEX, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_asset_hash_index(index: dict) -> None:
    ASSET_HASH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(ASSET_HASH_INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def hash_file(path: Path) -> str:
    """sha256 of file bytes, memoized by (path, mtime, size) to skip re-hashing unchanged files."""
    stat = path.stat()
    index = _load_asset_hash_index()
    cache_key = str(path.resolve())
    cached = index.get(cache_key)
    if cached and cached["mtime"] == stat.st_mtime and cached["size"] == stat.st_size:
        return cached["hash"]

    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    file_hash = digest.hexdigest()

    index[cache_key] = {"mtime": stat.st_mtime, "size": stat.st_size, "hash": file_hash}
    _save_asset_hash_index(index)
    return file_hash


def hash_asset(paths: list[Path]) -> str:
    """Combined hash for a creative unit (single file, or sorted carousel frames)."""
    combined = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.name):
        combined.update(hash_file(path).encode("utf-8"))
    return combined.hexdigest()


def build_cache_key(
    asset_hash: str,
    frame_set_hash: str,
    transcript_status: str,
    transcript_hash: str,
    provider: str,
    model: str,
    prompt_version: str,
    schema_version: str,
) -> str:
    """2026-09-12: transcript 상태/내용을 키에 포함시켜, transcript 없이 만들어진 vision 결과가
    나중에 transcript 생성이 성공한 뒤에도 그대로 재사용되는 일이 없게 한다. frame_set_hash는
    실제로 전송된 프레임 파일들의 해시라 frame 추출 로직/설정이 바뀌어도 캐시가 자동으로
    무효화된다 (asset_hash는 원본 소재 파일 자체의 해시라 이 경우 그대로일 수 있음)."""
    raw = (
        f"{asset_hash}|{frame_set_hash}|{transcript_status}|{transcript_hash}|"
        f"{provider}|{model}|{prompt_version}|{schema_version}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_transcript_cache_key(file_hash: str, whisper_model: str) -> str:
    """Hashed (not raw-concatenated) so the key is always filesystem-safe on Windows —
    a raw 'hash|model' string breaks path handling because '|' is an invalid filename char."""
    raw = f"{file_hash}|{whisper_model}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_cached_transcript(cache_key: str) -> dict | None:
    """Transcript cache is keyed only by (file hash, whisper model) — never by vision
    provider — so running the OpenAI benchmark then the Claude benchmark on the same
    videos does not pay for Whisper transcription twice (spec §15: 동일 입력조건 유지도
    비용 낭비 없이 지켜야 함)."""
    path = TRANSCRIPT_CACHE_DIR / f"{cache_key}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cached_transcript(cache_key: str, data: dict) -> None:
    TRANSCRIPT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPT_CACHE_DIR / f"{cache_key}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_cached_result(cache_key: str) -> CreativeAnalysisResult | None:
    path = ANALYSIS_CACHE_DIR / f"{cache_key}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return CreativeAnalysisResult.model_validate(data)


def save_cached_result(cache_key: str, result: CreativeAnalysisResult) -> None:
    ANALYSIS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = ANALYSIS_CACHE_DIR / f"{cache_key}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)
