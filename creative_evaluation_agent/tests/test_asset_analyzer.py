"""Regression tests:
1. CreativeObservation must accept 'not_observed' for every enum field the prompt promises
   it for (message_density/immediate_understandability/cut_pace) — a real Claude run hit
   exactly this validation error because the schema didn't allow it.
2. A failed analysis (API_ERROR/PARSE_ERROR) must never be cached, or it would be returned
   as a permanent "CACHE_HIT" on every future run and never actually retried.
3. A vision result produced while a video had no transcript must NOT be reused once a
   transcript later becomes available for that same video (2026-09-12 cache-key redesign).
"""
import subprocess
from types import SimpleNamespace

import imageio_ffmpeg
from PIL import Image

from src import asset_analyzer, audio_extraction, cache
from src.blind_mapper import MappingRow
from src.providers.base import CreativeObservation
from tests.fake_provider import FakeProvider


def test_creative_observation_accepts_not_observed_for_enum_fields():
    obs = CreativeObservation(
        asset_type="video",
        first_3sec_core_element="x",
        hook_type="x",
        main_visual_focus="x",
        offer_present=False,
        demo_present=False,
        actual_color_or_makeup_result="x",
        before_after_present=False,
        person_type="none",
        proof_type="x",
        subtitle_prominence="x",
        core_message="x",
        message_density="not_observed",
        immediate_understandability="not_observed",
        cta_type="x",
        brand_or_product_name_exposure="x",
        cut_pace="not_observed",
    )
    assert obs.cut_pace == "not_observed"
    assert obs.message_density == "not_observed"
    assert obs.immediate_understandability == "not_observed"


def _patch_cache_paths(monkeypatch, tmp_path):
    asset_hash_dir = tmp_path / "cache" / "asset_hashes"
    analysis_cache_dir = tmp_path / "cache" / "creative_analysis"
    monkeypatch.setattr(cache, "ASSET_HASH_CACHE_DIR", asset_hash_dir)
    monkeypatch.setattr(cache, "ASSET_HASH_INDEX", asset_hash_dir / "index.json")
    monkeypatch.setattr(cache, "ANALYSIS_CACHE_DIR", analysis_cache_dir)
    monkeypatch.setattr(cache, "TRANSCRIPT_CACHE_DIR", analysis_cache_dir / "transcripts")
    monkeypatch.setattr(asset_analyzer, "BENCHMARK_RESULTS_DIR", tmp_path / "benchmark" / "results")
    monkeypatch.setattr(audio_extraction, "AUDIO_STAGING_DIR", tmp_path / "cache" / "audio_staging")


def test_failed_analysis_is_not_cached_and_is_retried_next_time(tmp_path, monkeypatch):
    _patch_cache_paths(monkeypatch, tmp_path)

    image_path = tmp_path / "asset_001.jpg"
    Image.new("RGB", (100, 100), (1, 2, 3)).save(image_path)
    row = MappingRow(
        blind_id="asset_001", original_media="M", original_creative_name="C",
        original_file_name="C.jpg", asset_type="image",
        original_path=str(image_path), blind_path=str(image_path),
    )

    failing_provider = FakeProvider(name="claude", fail_with_status="PARSE_ERROR")
    result1 = asset_analyzer.analyze_one(row, failing_provider, "prompt", tmp_path / "frames")
    assert result1.raw_status == "PARSE_ERROR"
    assert failing_provider.call_count == 1

    # Retrying (e.g. next day's run) must call the provider again — not return a fake cache hit.
    result2 = asset_analyzer.analyze_one(row, failing_provider, "prompt", tmp_path / "frames")
    assert result2.raw_status == "PARSE_ERROR"
    assert failing_provider.call_count == 2  # incremented -> proves it wasn't served from cache


def test_successful_analysis_is_cached_and_not_recalled(tmp_path, monkeypatch):
    _patch_cache_paths(monkeypatch, tmp_path)

    image_path = tmp_path / "asset_002.jpg"
    Image.new("RGB", (100, 100), (4, 5, 6)).save(image_path)
    row = MappingRow(
        blind_id="asset_002", original_media="M", original_creative_name="C",
        original_file_name="C.jpg", asset_type="image",
        original_path=str(image_path), blind_path=str(image_path),
    )

    provider = FakeProvider(name="openai")
    result1 = asset_analyzer.analyze_one(row, provider, "prompt", tmp_path / "frames")
    assert result1.raw_status == "OK"
    assert provider.call_count == 1

    result2 = asset_analyzer.analyze_one(row, provider, "prompt", tmp_path / "frames")
    assert result2.raw_status == "OK"
    assert provider.call_count == 1  # unchanged -> served from cache


def _make_video_with_audio(path, seconds=2):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"color=c=yellow:s=64x48:d={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-c:v", "libx264", "-c:a", "aac", "-shortest",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)


def test_vision_result_without_transcript_is_not_reused_once_transcript_succeeds(tmp_path, monkeypatch):
    """The exact bug being fixed: a video analyzed while its transcript was unavailable must
    be reprocessed (not silently served from cache) once a transcript becomes available."""
    _patch_cache_paths(monkeypatch, tmp_path)

    video_path = tmp_path / "asset_010.mp4"
    _make_video_with_audio(video_path)
    row = MappingRow(
        blind_id="asset_010", original_media="M", original_creative_name="C",
        original_file_name="C.mp4", asset_type="video",
        original_path=str(video_path), blind_path=str(video_path),
    )
    provider = FakeProvider(name="openai")

    # Attempt 1: no OPENAI_API_KEY -> transcript step fails (API_ERROR), vision analysis
    # still proceeds without a transcript and gets cached under that condition.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result1 = asset_analyzer.analyze_one(row, provider, "prompt", tmp_path / "frames")
    assert result1.raw_status == "OK"
    assert result1.transcript_available is False
    assert provider.call_count == 1

    # Attempt 2: transcript now succeeds (API key present, Whisper mocked) -> this must NOT
    # be served from the attempt-1 cache entry; the provider must be called again with the
    # transcript actually included this time.
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    class _FakeTranscriptions:
        def create(self, **kwargs):
            return SimpleNamespace(text="now we have real speech")

    class _FakeOpenAI:
        def __init__(self, api_key):
            self.audio = SimpleNamespace(transcriptions=_FakeTranscriptions())

    import openai

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)

    result2 = asset_analyzer.analyze_one(row, provider, "prompt", tmp_path / "frames")
    assert result2.raw_status == "OK"
    assert result2.transcript_available is True
    assert result2.transcript_status == "OK"
    assert provider.call_count == 2  # proves attempt 2 was NOT served from attempt 1's cache
