"""End-to-end Benchmark Harness dry-run: prepare -> cost estimate -> fake analyze -> cache ->
ground truth lock -> comparison. No real network call anywhere in this test.
"""
from PIL import Image

from src import asset_analyzer, benchmark_runner, blind_mapper, cache, comparison, ground_truth
from tests.fake_provider import FakeProvider


def _make_fixture_image(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color=(120, 120, 120)).save(path)


def _patch_all_paths(monkeypatch, tmp_path):
    source_assets = tmp_path / "benchmark" / "source_assets"
    blind_assets = tmp_path / "benchmark" / "blind_assets"
    mapping_path = tmp_path / "benchmark" / "mapping" / "benchmark_asset_map.xlsx"
    results_dir = tmp_path / "benchmark" / "results"
    ground_truth_path = tmp_path / "benchmark" / "ground_truth" / "hidden_ground_truth.xlsx"
    comparison_path = results_dir / "comparison" / "comparison_report.xlsx"
    frame_cache_dir = tmp_path / "cache" / "frames"
    asset_hash_dir = tmp_path / "cache" / "asset_hashes"
    analysis_cache_dir = tmp_path / "cache" / "creative_analysis"

    monkeypatch.setattr(blind_mapper, "SOURCE_ASSETS_DIR", source_assets)
    monkeypatch.setattr(blind_mapper, "BLIND_ASSETS_DIR", blind_assets)
    monkeypatch.setattr(blind_mapper, "MAPPING_PATH", mapping_path)

    monkeypatch.setattr(asset_analyzer, "BENCHMARK_RESULTS_DIR", results_dir)
    monkeypatch.setattr(benchmark_runner, "BENCHMARK_RESULTS_DIR", results_dir)
    monkeypatch.setattr(benchmark_runner, "FRAME_CACHE_DIR", frame_cache_dir)

    monkeypatch.setattr(ground_truth, "GROUND_TRUTH_PATH", ground_truth_path)
    monkeypatch.setattr(comparison, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(comparison, "COMPARISON_PATH", comparison_path)

    monkeypatch.setattr(cache, "ASSET_HASH_CACHE_DIR", asset_hash_dir)
    monkeypatch.setattr(cache, "ASSET_HASH_INDEX", asset_hash_dir / "index.json")
    monkeypatch.setattr(cache, "ANALYSIS_CACHE_DIR", analysis_cache_dir)

    return source_assets, ground_truth_path


def test_full_dryrun_and_cache_and_ground_truth_lock(tmp_path, monkeypatch):
    source_assets, ground_truth_path = _patch_all_paths(monkeypatch, tmp_path)

    _make_fixture_image(source_assets / "메타" / "소재A.jpg")

    mapping_rows = blind_mapper.prepare_blind_assets()
    assert len(mapping_rows) == 1
    assert mapping_rows[0].blind_id == "asset_001"
    assert mapping_rows[0].original_media == "메타"
    assert mapping_rows[0].original_creative_name == "소재A"

    openai_fake = FakeProvider(name="openai", predicted_response="HIGH")
    claude_fake = FakeProvider(name="claude", predicted_response="LOW")

    # Dry-run must never call analyze()
    dry_result = benchmark_runner.run_provider(openai_fake, dry_run=True)
    assert dry_result["status"] == "DRY_RUN"
    assert dry_result["new_count"] == 1
    assert openai_fake.call_count == 0

    # Ground truth must be locked before either provider is done
    assert ground_truth.is_unlocked() is False

    monkeypatch.setattr(benchmark_runner, "prompt_approval", lambda: True)

    result = benchmark_runner.run_provider(openai_fake, dry_run=False)
    assert result["status"] == "OK"
    assert openai_fake.call_count == 1
    assert benchmark_runner.is_provider_done("openai") is True

    # Re-running must hit cache, not call the provider again
    result_again = benchmark_runner.run_provider(openai_fake, dry_run=False)
    assert result_again["status"] == "OK"
    assert openai_fake.call_count == 1  # unchanged -> cache hit

    # Still locked: claude not done yet
    assert ground_truth.is_unlocked() is False
    try:
        ground_truth.load_ground_truth()
        assert False, "잠금 상태에서 ground truth를 읽을 수 있으면 안 된다"
    except ground_truth.GroundTruthLockedError:
        pass

    benchmark_runner.run_provider(claude_fake, dry_run=False)
    assert ground_truth.is_unlocked() is True

    # Now write ground truth and run comparison
    from openpyxl import Workbook

    ground_truth_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.append(["Blind_ID", "Observed_Performance"])
    ws.append(["asset_001", "ABOVE_BENCHMARK"])
    wb.save(ground_truth_path)

    detail_rows, summaries = comparison.build_comparison()
    assert len(detail_rows) == 1
    row = detail_rows[0]
    assert row["OpenAI_Predicted_Response"] == "HIGH"
    assert row["OpenAI_Direction_Status"] == "PREDICTION_MATCH_HIGH"
    assert row["Claude_Predicted_Response"] == "LOW"
    assert row["Claude_Direction_Status"] == "AI_MISSED_WINNER"

    report_path = comparison.export_comparison_report()
    assert report_path.exists()


def test_no_approval_means_no_analyze_call(tmp_path, monkeypatch):
    source_assets, _ = _patch_all_paths(monkeypatch, tmp_path)
    _make_fixture_image(source_assets / "메타" / "소재B.jpg")
    blind_mapper.prepare_blind_assets()

    fake = FakeProvider(name="openai")
    monkeypatch.setattr(benchmark_runner, "prompt_approval", lambda: False)

    result = benchmark_runner.run_provider(fake, dry_run=False)
    assert result["status"] == "CANCELLED"
    assert fake.call_count == 0
