"""Engine 01 end-to-end orchestration: input -> 01 Excel in output/latest + output/archive."""
from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from src.benchmark import compute_benchmarks
from src.evaluator import evaluate_all
from src.exporter import export_engine01, export_engine02_skeleton, export_engine03_skeleton
from src.loader import InputDataError, find_input_excel, load_ad_data, scan_asset_inventory
from src.matcher import match_all
from src.scale import compute_scale
from src.validator import validate_rows
from src.winner_interpretation import compute_winner_interpretation

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_LATEST_DIR = PROJECT_ROOT / "output" / "latest"
OUTPUT_ARCHIVE_DIR = PROJECT_ROOT / "output" / "archive"

ENGINE01_FILENAME = "01_Creative_Performance_Evaluation.xlsx"
ENGINE02_FILENAME = "02_Creative_Content_Analysis.xlsx"
ENGINE03_FILENAME = "03_Integrated_Creative_Evaluation.xlsx"


def run_engine01() -> dict:
    """Runs Engine 01 and writes all three report files (02/03 as schema skeletons)."""
    try:
        excel_path = find_input_excel()
    except InputDataError as e:
        logger.error(str(e))
        return {"status": "PARSE_ERROR", "message": str(e)}

    logger.info("광고 운영 데이터 로드: %s", excel_path)
    rows = load_ad_data(excel_path)
    logger.info("로드된 행 수: %d", len(rows))

    issues = validate_rows(rows)
    if issues:
        logger.warning("검증 이슈 %d건 발견 (CHECK 등, 리포트에 상태값으로 남김)", len(issues))
        for issue in issues[:20]:
            logger.warning("  row=%s creative_id=%s codes=%s", issue.row_number, issue.creative_id, issue.codes)
        if len(issues) > 20:
            logger.warning("  ... 외 %d건 더 있음", len(issues) - 20)

    assets = scan_asset_inventory()
    logger.info("소재 인벤토리 스캔 완료: %d건", len(assets))
    matches = match_all(rows, assets)

    not_found = sum(1 for m in matches.values() if m.status == "ASSET_NOT_FOUND")
    multiple = sum(1 for m in matches.values() if m.status == "MULTIPLE_ASSET_MATCH")
    if not_found:
        logger.warning("ASSET_NOT_FOUND: %d행", not_found)
    if multiple:
        logger.warning("MULTIPLE_ASSET_MATCH: %d행", multiple)

    benchmarks = compute_benchmarks(rows)
    scale = compute_scale(rows)
    evaluations = evaluate_all(rows, benchmarks, scale)
    winner_interpretations = compute_winner_interpretation(evaluations)

    asset_match_status = {row.Creative_ID: matches[row.row_number].status for row in rows}

    OUTPUT_LATEST_DIR.mkdir(parents=True, exist_ok=True)
    engine01_path = OUTPUT_LATEST_DIR / ENGINE01_FILENAME
    export_engine01(evaluations, asset_match_status, winner_interpretations, engine01_path)
    logger.info("생성 완료: %s", engine01_path)

    engine02_path = OUTPUT_LATEST_DIR / ENGINE02_FILENAME
    export_engine02_skeleton(engine02_path)
    engine03_path = OUTPUT_LATEST_DIR / ENGINE03_FILENAME
    export_engine03_skeleton(engine03_path)
    logger.info("02/03 스키마 골격 생성 완료 (Phase 3/6 대상, 이번 실행은 골격만)")

    archive_dir = OUTPUT_ARCHIVE_DIR / datetime.now().strftime("%Y-%m-%d_%H%M")
    archive_dir.mkdir(parents=True, exist_ok=True)
    for f in (engine01_path, engine02_path, engine03_path):
        shutil.copy2(f, archive_dir / f.name)
    logger.info("아카이브 저장 완료: %s", archive_dir)

    classification_counts: dict[str, int] = {}
    for ev in evaluations:
        classification_counts[ev.final_classification] = classification_counts.get(ev.final_classification, 0) + 1

    return {
        "status": "OK",
        "row_count": len(rows),
        "validation_issue_count": len(issues),
        "asset_not_found_count": not_found,
        "multiple_asset_match_count": multiple,
        "classification_counts": classification_counts,
        "engine01_path": str(engine01_path),
        "engine02_path": str(engine02_path),
        "engine03_path": str(engine03_path),
        "archive_dir": str(archive_dir),
    }
