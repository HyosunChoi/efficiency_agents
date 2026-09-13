"""Matches ad-data rows to asset inventory by 매체+소재명 only (spec §4).

No fuzzy/semantic matching. Ambiguity is reported as an explicit status
(ASSET_NOT_FOUND / MULTIPLE_ASSET_MATCH / CHECK), never silently guessed.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.loader import AdRow, AssetEntry
from src.normalizer import normalize_name

ASSET_NOT_FOUND = "ASSET_NOT_FOUND"
MULTIPLE_ASSET_MATCH = "MULTIPLE_ASSET_MATCH"
MATCHED = "MATCHED"
CHECK = "CHECK"


@dataclass
class MatchResult:
    status: str
    asset: AssetEntry | None = None
    candidates: list[AssetEntry] | None = None


def _index_assets(assets: list[AssetEntry]) -> dict[tuple[str, str], list[AssetEntry]]:
    index: dict[tuple[str, str], list[AssetEntry]] = {}
    for asset in assets:
        key = (
            normalize_name(asset.media_folder_raw),
            normalize_name(asset.creative_key_raw),
        )
        index.setdefault(key, []).append(asset)
    return index


def match_row(row: AdRow, asset_index: dict[tuple[str, str], list[AssetEntry]]) -> MatchResult:
    key = (row.Media_Normalized, row.Creative_Name_Normalized)
    candidates = asset_index.get(key, [])

    if len(candidates) == 0:
        return MatchResult(status=ASSET_NOT_FOUND)
    if len(candidates) == 1:
        return MatchResult(status=MATCHED, asset=candidates[0])
    return MatchResult(status=MULTIPLE_ASSET_MATCH, candidates=candidates)


def match_all(rows: list[AdRow], assets: list[AssetEntry]) -> dict[int, MatchResult]:
    """Returns {row_number: MatchResult}."""
    asset_index = _index_assets(assets)
    return {row.row_number: match_row(row, asset_index) for row in rows}
