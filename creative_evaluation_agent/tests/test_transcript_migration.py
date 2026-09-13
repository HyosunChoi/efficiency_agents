"""transcript_migration.py must, without ever calling Whisper or a vision provider:
- leave images/carousels untouched (no transcript concept, trivially unaffected)
- migrate videos whose transcript already succeeded before, reusing the legacy text
- correctly predict (via real local audio extraction) that a previously-failed video will
  now succeed, and leave that one as a genuine cache miss for real reprocessing
- actually perform the migration (copy cache entries forward) only for the unaffected set
"""
import subprocess
from pathlib import Path

import imageio_ffmpeg
from openpyxl import Workbook

from src import audio_extraction, blind_mapper, cache, transcript_migration as tm
from src.providers.base import CreativeAnalysisResult, CreativeObservation
from tests.fake_provider import FakeProvider


def _make_video_with_audio(path, seconds=2):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"color=c=cyan:s=64x48:d={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-c:v", "libx264", "-c:a", "aac", "-shortest",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)


def _make_silent_video(path, seconds=2):
    import cv2
    import numpy as np

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, 10, (64, 48))
    for i in range(seconds * 10):
        writer.write(np.full((48, 64, 3), i % 255, dtype=np.uint8))
    writer.release()


def _fake_result(blind_id: str, provider: str, model: str) -> CreativeAnalysisResult:
    return CreativeAnalysisResult(
        schema_version="v1", prompt_version="v1", blind_id=blind_id, provider=provider, model=model,
        observation=CreativeObservation(
            asset_type="video", first_3sec_core_element="x", hook_type="x", main_visual_focus="x",
            offer_present=False, demo_present=False, actual_color_or_makeup_result="x",
            before_after_present=False, person_type="none", proof_type="x", subtitle_prominence="x",
            core_message="x", message_density="low", immediate_understandability="high",
            cta_type="x", brand_or_product_name_exposure="x", cut_pace="medium",
        ),
        ai_predicted_response="HIGH", ai_confidence="HIGH",
        reason_1="r1", reason_2="r2", reason_3="r3", uncertainty_or_limitations="none",
        raw_status="OK",
    )


def _setup(tmp_path, monkeypatch):
    # mapping + blind assets on disk
    mapping_path = tmp_path / "mapping.xlsx"
    monkeypatch.setattr(blind_mapper, "MAPPING_PATH", mapping_path)

    image_path = tmp_path / "asset_001.jpg"
    from PIL import Image
    Image.new("RGB", (50, 50), (1, 2, 3)).save(image_path)

    legacy_ok_video = tmp_path / "asset_002.mp4"
    _make_video_with_audio(legacy_ok_video)

    predicted_ok_video = tmp_path / "asset_003.mov"  # was failing before (mov + no legacy transcript)
    _make_video_with_audio(predicted_ok_video)

    still_silent_video = tmp_path / "asset_004.mp4"
    _make_silent_video(still_silent_video)

    wb = Workbook()
    ws = wb.active
    ws.append(blind_mapper.MAPPING_COLUMNS)
    ws.append(["asset_001", "M", "img1", "img1.jpg", "image", str(image_path), str(image_path)])
    ws.append(["asset_002", "M", "vid_ok", "vid_ok.mp4", "video", str(legacy_ok_video), str(legacy_ok_video)])
    ws.append(["asset_003", "M", "vid_new", "vid_new.mov", "video", str(predicted_ok_video), str(predicted_ok_video)])
    ws.append(["asset_004", "M", "vid_silent", "vid_silent.mp4", "video", str(still_silent_video), str(still_silent_video)])
    wb.save(mapping_path)

    # cache paths
    asset_hash_dir = tmp_path / "cache" / "asset_hashes"
    analysis_cache_dir = tmp_path / "cache" / "creative_analysis"
    monkeypatch.setattr(cache, "ASSET_HASH_CACHE_DIR", asset_hash_dir)
    monkeypatch.setattr(cache, "ASSET_HASH_INDEX", asset_hash_dir / "index.json")
    monkeypatch.setattr(cache, "ANALYSIS_CACHE_DIR", analysis_cache_dir)
    monkeypatch.setattr(cache, "TRANSCRIPT_CACHE_DIR", analysis_cache_dir / "transcripts")
    monkeypatch.setattr(audio_extraction, "AUDIO_STAGING_DIR", tmp_path / "cache" / "audio_staging")
    monkeypatch.setattr(tm, "FRAME_CACHE_DIR", tmp_path / "cache" / "frames")
    monkeypatch.setattr(tm, "ANALYSIS_CACHE_DIR", analysis_cache_dir)

    providers = [FakeProvider(name="openai"), FakeProvider(name="claude")]

    # pre-populate OLD-style (legacy 5-component) vision cache for all 4 assets, both providers
    from src.blind_mapper import load_mapping

    for row in load_mapping():
        asset_hash = cache.hash_asset([Path(row.blind_path)])
        for provider in providers:
            old_key = tm._legacy_vision_cache_key(asset_hash, provider.name, provider.model, "v1", "v1")
            result = _fake_result(row.blind_id, provider.name, provider.model)
            (analysis_cache_dir).mkdir(parents=True, exist_ok=True)
            with open(analysis_cache_dir / f"{old_key}.json", "w", encoding="utf-8") as f:
                f.write(result.model_dump_json())

    # pre-populate legacy transcript cache (pre-pipeline-version) for asset_002 only
    from src.cache import build_transcript_cache_key, hash_file, save_cached_transcript

    legacy_key = build_transcript_cache_key(hash_file(legacy_ok_video), "whisper-1")
    save_cached_transcript(legacy_key, {"text": "legacy narration text", "status": "OK"})

    return providers


def test_migration_plan_categorizes_all_four_assets_correctly(tmp_path, monkeypatch):
    providers = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(tm, "get_model_config", lambda: {
        "prompt_version": "v1", "schema_version": "v1",
        "transcript": {"model": "whisper-1", "max_file_size_mb": 25},
    })

    summary = tm.plan_migration(providers)
    by_id = {(p.blind_id, p.provider): p for p in summary.plans}

    for provider_name in ("openai", "claude"):
        assert by_id[("asset_001", provider_name)].category == tm.UNCHANGED_NOT_APPLICABLE
        assert by_id[("asset_002", provider_name)].category == tm.UNCHANGED_REUSED_LEGACY
        assert by_id[("asset_003", provider_name)].category == tm.CHANGED_NEW_TRANSCRIPT_PREDICTED
        assert by_id[("asset_004", provider_name)].category == tm.UNCHANGED_STILL_NO_TRANSCRIPT

    assert summary.reprocess_blind_ids("openai") == ["asset_003"]
    assert summary.reprocess_blind_ids("claude") == ["asset_003"]


def test_apply_migration_copies_unaffected_and_skips_changed(tmp_path, monkeypatch):
    providers = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(tm, "get_model_config", lambda: {
        "prompt_version": "v1", "schema_version": "v1",
        "transcript": {"model": "whisper-1", "max_file_size_mb": 25},
    })

    summary = tm.plan_migration(providers)
    stats = tm.apply_migration(summary)

    # 3 unaffected assets x 2 providers = 6 migrated; asset_003 x 2 providers = 2 left for reprocessing
    assert stats["migrated"] == 6
    assert stats["left_for_reprocessing"] == 2

    from src.cache import get_cached_result

    for p in summary.plans:
        if p.category == tm.NO_PRIOR_RESULT:
            continue
        new_key = cache.build_cache_key(
            p.asset_hash, p.frame_set_hash, p.new_transcript_status, p.new_transcript_hash,
            p.provider, providers[0].model if p.provider == "openai" else providers[1].model,
            "v1", "v1",
        )
        cached = get_cached_result(new_key)
        if p.category == tm.CHANGED_NEW_TRANSCRIPT_PREDICTED:
            assert cached is None, f"{p.blind_id}/{p.provider} should NOT have been migrated"
        else:
            assert cached is not None, f"{p.blind_id}/{p.provider} should have been migrated"
