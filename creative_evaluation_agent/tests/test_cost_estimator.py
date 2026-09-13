"""Regression tests for cost estimation: videos must be costed using their real frame
resolution and an accurate frame count (not "1 image" per video), Whisper transcript cost
must be shared (cached) across providers rather than paid twice, and the per-provider
report must carry the detailed breakdown (tokens/prices/formula) the approval screen shows.
"""
import subprocess

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image

from src import cache
from src.blind_mapper import MappingRow
from src.cost_estimator import (
    _estimate_video_frame_count,
    _frame_dimensions_for_asset,
    _video_metadata,
    build_cost_report,
    build_whisper_cost_report,
)
from tests.fake_provider import FakeProvider


def _make_synthetic_video(path, seconds=6, fps=10, width=64, height=48):
    """Video-only, no audio track — used by tests that only care about frames/dimensions."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
    for i in range(seconds * fps):
        frame = np.full((height, width, 3), (i * 3) % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()


def _make_video_with_audio(path, seconds=3):
    """Real video+audio via ffmpeg's synthetic lavfi sources — for transcript-pipeline tests."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"color=c=blue:s=64x48:d={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-c:v", "libx264", "-c:a", "aac", "-shortest",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)


def _patch_cache_paths(monkeypatch, tmp_path):
    asset_hash_dir = tmp_path / "cache" / "asset_hashes"
    analysis_cache_dir = tmp_path / "cache" / "creative_analysis"
    transcript_cache_dir = analysis_cache_dir / "transcripts"
    monkeypatch.setattr(cache, "ASSET_HASH_CACHE_DIR", asset_hash_dir)
    monkeypatch.setattr(cache, "ASSET_HASH_INDEX", asset_hash_dir / "index.json")
    monkeypatch.setattr(cache, "ANALYSIS_CACHE_DIR", analysis_cache_dir)
    monkeypatch.setattr(cache, "TRANSCRIPT_CACHE_DIR", transcript_cache_dir)

    from src import audio_extraction

    monkeypatch.setattr(audio_extraction, "AUDIO_STAGING_DIR", tmp_path / "cache" / "audio_staging")


def test_video_frame_count_estimate_accounts_for_multiple_frames_not_just_one(tmp_path):
    video_path = tmp_path / "clip.mp4"
    _make_synthetic_video(video_path, seconds=6, fps=10)  # long enough for all fixed timestamps

    duration_sec, width, height = _video_metadata(video_path)
    assert width == 64 and height == 48
    count = _estimate_video_frame_count(duration_sec)

    # 6s clip covers every fixed candidate (0,0.5,1.5,3,5) + last + up to max_scene_change_frames(5)
    # i.e. it must be well above the old (buggy) estimate of 1 "image" per video.
    assert count > 1
    assert count >= 6  # 5 fixed timestamps fit + last frame, at minimum


def test_frame_dimensions_use_real_video_resolution_not_a_flat_guess(tmp_path):
    video_path = tmp_path / "clip.mp4"
    _make_synthetic_video(video_path, seconds=2, fps=10, width=320, height=240)

    row = MappingRow(
        blind_id="asset_001", original_media="M", original_creative_name="C",
        original_file_name="C.mp4", asset_type="video",
        original_path=str(video_path), blind_path=str(video_path),
    )
    dims = _frame_dimensions_for_asset(row)
    assert len(dims) > 1
    assert all(d == (320, 240) for d in dims)


def test_frame_dimensions_for_image_reads_actual_file_size(tmp_path):
    image_path = tmp_path / "asset_002.jpg"
    Image.new("RGB", (500, 300), (10, 20, 30)).save(image_path)

    row = MappingRow(
        blind_id="asset_002", original_media="M", original_creative_name="C",
        original_file_name="C.jpg", asset_type="image",
        original_path=str(image_path), blind_path=str(image_path),
    )
    dims = _frame_dimensions_for_asset(row)
    assert dims == [(500, 300)]


def test_whisper_cost_is_shared_across_providers_via_cache(tmp_path, monkeypatch):
    _patch_cache_paths(monkeypatch, tmp_path)

    video_path = tmp_path / "blind_video.mp4"
    _make_video_with_audio(video_path, seconds=3)

    row = MappingRow(
        blind_id="asset_001",
        original_media="M",
        original_creative_name="C",
        original_file_name="C.mp4",
        asset_type="video",
        original_path=str(video_path),
        blind_path=str(video_path),
    )

    # First time: no transcript cached yet -> counted as a new (billable) Whisper call
    # (real, local audio extraction confirms this video has audio well under the size limit).
    report_before = build_whisper_cost_report([row])
    assert report_before.new_count == 1
    assert report_before.cached_count == 0
    assert report_before.estimated_cost_usd > 0

    # Simulate the OpenAI benchmark run having already produced+cached this transcript
    # (under the CURRENT pipeline's key, not the legacy one).
    from src.config_loader import get_model_config
    from src.transcript import transcript_cache_key_for

    whisper_model = get_model_config()["transcript"]["model"]
    cache_key = transcript_cache_key_for(cache.hash_file(video_path), whisper_model)
    cache.save_cached_transcript(cache_key, {"text": "fake transcript", "status": "OK"})

    # Now a second (e.g. Claude) benchmark run must see it as cached, not billed again.
    report_after = build_whisper_cost_report([row])
    assert report_after.new_count == 0
    assert report_after.cached_count == 1
    assert report_after.estimated_cost_usd == 0


def test_video_with_no_audio_stream_is_not_billed(tmp_path, monkeypatch):
    _patch_cache_paths(monkeypatch, tmp_path)

    video_path = tmp_path / "silent.mp4"
    _make_synthetic_video(video_path, seconds=2, fps=10)  # cv2-written video has no audio track

    row = MappingRow(
        blind_id="asset_002", original_media="M", original_creative_name="C",
        original_file_name="C.mp4", asset_type="video",
        original_path=str(video_path), blind_path=str(video_path),
    )

    report = build_whisper_cost_report([row])
    assert report.new_count == 0
    assert report.cached_count == 0
    assert report.estimated_cost_usd == 0


def test_provider_cost_report_carries_detailed_breakdown_fields(tmp_path, monkeypatch):
    _patch_cache_paths(monkeypatch, tmp_path)

    image_path = tmp_path / "asset_003.jpg"
    Image.new("RGB", (400, 400), (1, 2, 3)).save(image_path)
    row = MappingRow(
        blind_id="asset_003", original_media="M", original_creative_name="C",
        original_file_name="C.jpg", asset_type="image",
        original_path=str(image_path), blind_path=str(image_path),
    )

    provider = FakeProvider(name="openai")
    report = build_cost_report([row], provider)

    assert report.new_count == 1
    assert report.model == provider.model
    assert report.input_price_per_1k == provider.pricing["input_per_1k_tokens"]
    assert report.output_price_per_1k == provider.pricing["output_per_1k_tokens"]
    assert report.estimated_input_tokens > 0
    assert report.estimated_output_tokens == provider.pricing["est_output_tokens_per_analysis"]
    assert report.image_token_formula == provider.image_token_formula_description()
    assert report.estimated_cost_usd > 0
