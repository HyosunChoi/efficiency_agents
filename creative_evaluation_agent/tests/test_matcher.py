from pathlib import Path

from src.loader import AssetEntry
from src.matcher import ASSET_NOT_FOUND, MATCHED, MULTIPLE_ASSET_MATCH, match_all
from tests.factories import make_row


def test_matched_when_single_asset_exists():
    row = make_row(2, "무글틴", "전환", "싱글원_메타", "무글틴_1+1_0828", 100, 10, 1000, 1, 1000)
    assets = [
        AssetEntry(
            media_folder_raw="싱글원_메타",
            creative_key_raw="무글틴_1+1_0828",
            asset_type="video",
            paths=[Path("input/assets/싱글원_메타/무글틴_1+1_0828.mp4")],
        )
    ]
    results = match_all([row], assets)
    assert results[2].status == MATCHED
    assert results[2].asset is not None


def test_asset_not_found_when_no_match():
    row = make_row(2, "무글틴", "전환", "싱글원_메타", "존재안함", 100, 10, 1000, 1, 1000)
    results = match_all([row], [])
    assert results[2].status == ASSET_NOT_FOUND


def test_multiple_asset_match_when_duplicate_names():
    row = make_row(2, "무글틴", "전환", "싱글원_메타", "무글틴_1+1_0828", 100, 10, 1000, 1, 1000)
    assets = [
        AssetEntry("싱글원_메타", "무글틴_1+1_0828", "video", [Path("a.mp4")]),
        AssetEntry("싱글원_메타", "무글틴_1+1_0828", "image", [Path("a.jpg")]),
    ]
    results = match_all([row], assets)
    assert results[2].status == MULTIPLE_ASSET_MATCH
    assert len(results[2].candidates) == 2
