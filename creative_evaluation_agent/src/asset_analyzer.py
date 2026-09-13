"""One blind asset -> frames/transcript -> provider call -> cache + result file (spec §6/§8/§9).

The payload built here (CreativeAnalysisInput) structurally has no field for performance
data, so there is nothing to accidentally leak to the provider (spec §6 블라인드 원칙).

2026-09-12: frame extraction + transcript generation now happen BEFORE the vision-analysis
cache lookup (previously after), because the cache key itself depends on their outputs
(frame_set_hash, transcript_status, transcript_hash) — see cache.build_cache_key. This is
what guarantees a vision result produced without a transcript is never silently reused once
a transcript later becomes available for that same video.
"""
from __future__ import annotations

from pathlib import Path

from src.blind_mapper import MappingRow
from src.cache import build_cache_key, get_cached_result, hash_asset, save_cached_result
from src.config_loader import get_model_config
from src.frame_extractor import extract_frames
from src.providers.base import CreativeAnalysisInput, CreativeAnalysisResult, ProviderBase
from src.transcript import get_transcript

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_RESULTS_DIR = PROJECT_ROOT / "benchmark" / "results"

import logging

logger = logging.getLogger(__name__)


def _build_input(row: MappingRow, frame_cache_dir: Path) -> CreativeAnalysisInput:
    path = Path(row.blind_path)

    if row.asset_type == "carousel":
        frame_paths = sorted(str(p) for p in path.iterdir())
        return CreativeAnalysisInput(blind_id=row.blind_id, asset_type="carousel", frame_paths=frame_paths)

    if row.asset_type == "image":
        return CreativeAnalysisInput(blind_id=row.blind_id, asset_type="image", frame_paths=[str(path)])

    # video
    extracted = extract_frames(path, frame_cache_dir / row.blind_id)
    transcript = get_transcript(path)
    return CreativeAnalysisInput(
        blind_id=row.blind_id,
        asset_type="video",
        frame_paths=[str(f.path) for f in extracted],
        transcript_text=transcript.text,
        transcript_status=transcript.status,
        transcript_char_count=transcript.char_count,
        transcript_source=transcript.source or None,
        transcript_hash=transcript.transcript_hash or None,
        transcript_error_code=transcript.error_code,
        audio_extraction_status=transcript.audio_extraction_status,
    )


def _frame_set_hash(item: CreativeAnalysisInput) -> str:
    """실제로 provider에 전송되는 프레임 파일들의 해시. 원본 소재(asset_hash)가 같아도 프레임
    추출 설정이 바뀌면(scene-change threshold 등) 이 값이 달라져 캐시가 자동으로 무효화된다."""
    return hash_asset([Path(p) for p in item.frame_paths])


def analyze_one(row: MappingRow, provider: ProviderBase, prompt_text: str, frame_cache_dir: Path) -> CreativeAnalysisResult:
    cfg = get_model_config()
    prompt_version = cfg["prompt_version"]
    schema_version = cfg["schema_version"]

    paths_for_hash = sorted(Path(row.blind_path).iterdir()) if Path(row.blind_path).is_dir() else [Path(row.blind_path)]
    asset_hash = hash_asset(paths_for_hash)

    # frame/transcript는 캐시 키 계산에 필요해 조회보다 먼저 준비한다. 영상의 transcript가 아직
    # 캐시에 없으면 여기서 실제 Whisper 호출이 발생할 수 있다 — 이 함수는 (spec §7 승인 이후)
    # run_provider()가 사용자 승인을 받은 뒤에만 호출되므로 원칙은 지켜진다.
    item = _build_input(row, frame_cache_dir)
    frame_set_hash = _frame_set_hash(item)

    cache_key = build_cache_key(
        asset_hash,
        frame_set_hash,
        item.transcript_status,
        item.transcript_hash or "",
        provider.name,
        provider.model,
        prompt_version,
        schema_version,
    )

    cached = get_cached_result(cache_key)
    if cached is not None:
        logger.info("CACHE_HIT: %s (%s)", row.blind_id, provider.name)
        return cached

    result = provider.analyze(item, prompt_text)

    result = result.model_copy(
        update={
            "transcript_available": bool(item.transcript_text),
            "transcript_status": item.transcript_status,
            "transcript_char_count": item.transcript_char_count,
            "transcript_source": item.transcript_source,
            "transcript_hash": item.transcript_hash,
            "transcript_error_code": item.transcript_error_code,
            "audio_extraction_status": item.audio_extraction_status,
        }
    )

    if result.raw_status == "OK":
        save_cached_result(cache_key, result)
    else:
        # 실패(API_ERROR/PARSE_ERROR)는 캐시하지 않는다 — 캐시에 남으면 다음 실행에서 영원히
        # "CACHE_HIT"으로 재사용되어 재시도가 불가능해진다 (spec §12: 실패를 조용히 넘기지 않되,
        # 그 실패가 성공을 영구적으로 대체해서도 안 된다).
        logger.warning("%s (%s) 실패라 캐시하지 않음 — 다음 실행에서 재시도됨: %s", row.blind_id, provider.name, result.raw_status)

    result_dir = BENCHMARK_RESULTS_DIR / provider.name
    result_dir.mkdir(parents=True, exist_ok=True)
    with open(result_dir / f"{row.blind_id}.json", "w", encoding="utf-8") as f:
        f.write(result.model_dump_json(indent=2))

    return result
