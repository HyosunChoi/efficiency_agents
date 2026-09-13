"""Benchmark Harness 오케스트레이션: prepare / run (provider) / compare (spec §9).

실제 유료 API 호출은 run_provider()에서 사용자가 Y를 입력한 이후에만 발생한다.
"""
from __future__ import annotations

import logging
from pathlib import Path

from src.asset_analyzer import analyze_one
from src.blind_mapper import MappingRow, load_mapping, prepare_blind_assets
from src.cost_estimator import (
    build_cost_report,
    build_whisper_cost_report,
    print_approval_summary,
    prompt_approval,
)
from src.prompt_loader import load_benchmark_prompt_text
from src.providers.base import ProviderBase

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRAME_CACHE_DIR = PROJECT_ROOT / "cache" / "frames"
BENCHMARK_RESULTS_DIR = PROJECT_ROOT / "benchmark" / "results"

DONE_MARKER = "_DONE"


def run_prepare() -> list[MappingRow]:
    rows = prepare_blind_assets()
    logger.info("Blind asset 준비 완료: 총 %d건", len(rows))
    return rows


def run_provider(provider: ProviderBase, dry_run: bool = False) -> dict:
    mapping_rows = load_mapping()
    if not mapping_rows:
        logger.error("benchmark_asset_map.xlsx가 없습니다. 먼저 prepare를 실행하세요.")
        return {"status": "NO_ASSETS"}

    report = build_cost_report(mapping_rows, provider)
    whisper_report = build_whisper_cost_report(mapping_rows)
    print_approval_summary([report], len(mapping_rows), whisper_report=whisper_report)

    if dry_run:
        return {
            "status": "DRY_RUN",
            "new_count": report.new_count,
            "cached_count": report.cached_count,
            "estimated_cost_usd": report.estimated_cost_usd,
            "whisper_new_count": whisper_report.new_count,
            "whisper_estimated_cost_usd": whisper_report.estimated_cost_usd,
        }

    if report.new_count > 0 or whisper_report.new_count > 0:
        if not prompt_approval():
            logger.info("사용자가 취소했습니다. API 호출 없음.")
            return {"status": "CANCELLED"}
    else:
        logger.info("신규 분석 대상 없음 (전부 캐시 재사용). API 호출 없음.")

    prompt_text = load_benchmark_prompt_text()
    results = []
    for row in mapping_rows:
        result = analyze_one(row, provider, prompt_text, FRAME_CACHE_DIR)
        results.append(result)
        if result.raw_status != "OK":
            logger.warning("%s (%s): %s — %s", row.blind_id, provider.name, result.raw_status, result.error_detail)

    _mark_done(provider.name)
    return {"status": "OK", "results": results}


def _mark_done(provider_name: str) -> None:
    result_dir = BENCHMARK_RESULTS_DIR / provider_name
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / DONE_MARKER).touch()


def is_provider_done(provider_name: str) -> bool:
    return (BENCHMARK_RESULTS_DIR / provider_name / DONE_MARKER).exists()
