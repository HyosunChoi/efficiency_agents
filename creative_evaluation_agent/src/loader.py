"""Loads the ad performance Excel and inventories the input/assets folder.

Nothing here guesses at ambiguous input. Missing required columns are a hard failure
(PARSE_ERROR) rather than a silent skip; per-row numeric problems are tagged with an
explicit Row_Status instead of being coerced to 0 (spec §12: "분모가 0인 KPI는 임의
계산하지 않는다" and "조용히 추정하지 않는다").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from src.config_loader import get_column_aliases

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DATA_DIR = PROJECT_ROOT / "input" / "data"
INPUT_ASSETS_DIR = PROJECT_ROOT / "input" / "assets"

NUMERIC_FIELDS = ["Impressions", "Clicks", "Spend", "Conversions", "Revenue"]
VALID_ALLOCATION_CONTEXTS = {"AUTO", "MANUAL", "UNKNOWN"}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov"}
ASSET_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


class InputDataError(Exception):
    """Raised for structural problems that must stop the run (missing file/columns)."""


@dataclass
class AdRow:
    row_number: int  # 1-based excel row, for traceability
    Product: str = ""
    Objective_Raw: str = ""
    Media_Raw: str = ""
    Creative_Name_Raw: str = ""
    Media_Normalized: str = ""
    Creative_Name_Normalized: str = ""
    Creative_ID: str = ""
    Date: str | None = None
    Impressions: float | None = None
    Clicks: float | None = None
    Spend: float | None = None
    Conversions: float | None = None
    Revenue: float | None = None
    Allocation_Context: str = "UNKNOWN"  # AUTO | MANUAL | UNKNOWN (spec V2 §5) — optional column
    Row_Status: list[str] = field(default_factory=list)


@dataclass
class AssetEntry:
    """One matchable asset unit: a single file, or a folder of carousel frames."""

    media_folder_raw: str
    creative_key_raw: str  # filename stem (no ext) or folder name
    asset_type: str  # "image" | "video" | "carousel"
    paths: list[Path]  # 1 path for image/video, N sorted paths for carousel


def find_input_excel() -> Path:
    if not INPUT_DATA_DIR.exists():
        raise InputDataError(f"input/data 폴더가 없습니다: {INPUT_DATA_DIR}")

    candidates = sorted(
        p for p in INPUT_DATA_DIR.glob("*.xlsx") if not p.name.startswith("~$")
    )
    if len(candidates) == 0:
        raise InputDataError("input/data 폴더에 광고 운영 데이터 엑셀이 없습니다.")
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        raise InputDataError(
            f"input/data 폴더에 엑셀이 2개 이상 있습니다 (1개만 두세요): {names}"
        )
    return candidates[0]


def _build_header_index(header_row: list) -> dict[str, int]:
    """Map canonical field name -> column index, using column_aliases.yaml."""
    aliases = get_column_aliases()
    header_lookup = {
        str(cell).strip(): idx for idx, cell in enumerate(header_row) if cell is not None
    }

    field_to_index: dict[str, int] = {}
    for canonical, variants in aliases.items():
        if canonical == "required_fields":
            continue
        all_names = [canonical] + list(variants or [])
        for name in all_names:
            if name in header_lookup:
                field_to_index[canonical] = header_lookup[name]
                break

    required = aliases.get("required_fields", [])
    missing = [f for f in required if f not in field_to_index]
    if missing:
        raise InputDataError(
            "필수 컬럼을 찾을 수 없습니다: "
            + ", ".join(missing)
            + ". config/column_aliases.yaml 에 실제 헤더 표기를 추가하세요."
        )
    return field_to_index


def _parse_numeric(value, row_status: list[str], field_name: str) -> float | None:
    if value is None or value == "":
        row_status.append(f"CHECK:{field_name}_EMPTY")
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        row_status.append(f"CHECK:{field_name}_NOT_NUMERIC")
        return None


def load_ad_data(path: Path | None = None) -> list[AdRow]:
    from src.normalizer import (
        build_creative_id,
        normalize_creative_name,
        normalize_media,
    )

    path = path or find_input_excel()
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb.active

    rows_iter = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        raise InputDataError(f"엑셀이 비어 있습니다: {path}")

    field_index = _build_header_index(list(header_row))

    rows: list[AdRow] = []
    for excel_row_number, raw_row in enumerate(rows_iter, start=2):
        if raw_row is None or all(c is None for c in raw_row):
            continue  # trailing blank row, not a data issue

        def get(field_name: str):
            idx = field_index.get(field_name)
            return raw_row[idx] if idx is not None and idx < len(raw_row) else None

        row = AdRow(row_number=excel_row_number)
        row.Product = str(get("Product") or "").strip()
        row.Objective_Raw = str(get("Objective") or "").strip()
        row.Media_Raw = str(get("Media") or "").strip()
        row.Creative_Name_Raw = str(get("Creative_Name") or "").strip()
        date_val = get("Date")
        row.Date = str(date_val) if date_val is not None else None

        if not row.Product:
            row.Row_Status.append("CHECK:PRODUCT_EMPTY")
        if not row.Media_Raw:
            row.Row_Status.append("CHECK:MEDIA_EMPTY")
        if not row.Creative_Name_Raw:
            row.Row_Status.append("CHECK:CREATIVE_NAME_EMPTY")

        for f in NUMERIC_FIELDS:
            setattr(row, f, _parse_numeric(get(f), row.Row_Status, f))

        allocation_raw = str(get("Allocation_Context") or "").strip().upper()
        row.Allocation_Context = allocation_raw if allocation_raw in VALID_ALLOCATION_CONTEXTS else "UNKNOWN"

        row.Media_Normalized = normalize_media(row.Media_Raw)
        row.Creative_Name_Normalized = normalize_creative_name(row.Creative_Name_Raw)
        row.Creative_ID = build_creative_id(row.Media_Normalized, row.Creative_Name_Normalized)

        rows.append(row)

    wb.close()
    if not rows:
        raise InputDataError(f"엑셀에 데이터 행이 없습니다: {path}")
    return rows


def scan_asset_inventory(root_dir: Path | None = None) -> list[AssetEntry]:
    """Inventory <root_dir>/<매체명>/ into matchable units (single file or carousel folder).

    Defaults to input/assets/; benchmark harness reuses this against benchmark/source_assets/.
    """
    root_dir = root_dir or INPUT_ASSETS_DIR
    entries: list[AssetEntry] = []
    if not root_dir.exists():
        return entries

    for media_dir in sorted(p for p in root_dir.iterdir() if p.is_dir()):
        for item in sorted(media_dir.iterdir()):
            if item.is_dir():
                frame_files = sorted(
                    p for p in item.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS
                )
                if not frame_files:
                    continue
                entries.append(
                    AssetEntry(
                        media_folder_raw=media_dir.name,
                        creative_key_raw=item.name,
                        asset_type="carousel",
                        paths=frame_files,
                    )
                )
            elif item.is_file() and item.suffix.lower() in ASSET_EXTENSIONS:
                asset_type = "image" if item.suffix.lower() in IMAGE_EXTENSIONS else "video"
                entries.append(
                    AssetEntry(
                        media_folder_raw=media_dir.name,
                        creative_key_raw=item.stem,
                        asset_type=asset_type,
                        paths=[item],
                    )
                )
    return entries
