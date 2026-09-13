"""End-to-end get_transcript() pipeline: video -> audio extraction -> (mocked) Whisper ->
cached result — verifying the .mov/size problems are actually fixed and that the transcript
cache key is versioned so this pipeline change doesn't silently reuse pre-migration entries.
"""
import subprocess
from types import SimpleNamespace

import imageio_ffmpeg

from src import audio_extraction, transcript


def _make_video_with_audio(path, seconds=2, container="mp4"):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"color=c=green:s=64x48:d={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-c:v", "libx264", "-c:a", "aac", "-shortest",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)


def _patch_paths(monkeypatch, tmp_path):
    from src import cache

    asset_hash_dir = tmp_path / "cache" / "asset_hashes"
    analysis_cache_dir = tmp_path / "cache" / "creative_analysis"
    monkeypatch.setattr(cache, "ASSET_HASH_CACHE_DIR", asset_hash_dir)
    monkeypatch.setattr(cache, "ASSET_HASH_INDEX", asset_hash_dir / "index.json")
    monkeypatch.setattr(cache, "ANALYSIS_CACHE_DIR", analysis_cache_dir)
    monkeypatch.setattr(cache, "TRANSCRIPT_CACHE_DIR", analysis_cache_dir / "transcripts")
    monkeypatch.setattr(audio_extraction, "AUDIO_STAGING_DIR", tmp_path / "audio_staging")


class _FakeTranscriptions:
    def __init__(self, text):
        self.text = text
        self.call_count = 0

    def create(self, **kwargs):
        self.call_count += 1
        return SimpleNamespace(text=self.text)


class _FakeOpenAI:
    def __init__(self, transcriptions):
        self.audio = SimpleNamespace(transcriptions=transcriptions)


def test_mov_video_gets_a_real_transcript_via_audio_extraction(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    video_path = tmp_path / "clip.mov"  # the exact container Whisper used to reject outright
    _make_video_with_audio(video_path)

    fake_transcriptions = _FakeTranscriptions("hello from the ad")
    import openai

    monkeypatch.setattr(openai, "OpenAI", lambda api_key: _FakeOpenAI(fake_transcriptions))

    result = transcript.get_transcript(video_path)

    assert result.status == "OK"
    assert result.text == "hello from the ad"
    assert result.char_count == len("hello from the ad")
    assert result.transcript_hash == transcript.hash_text("hello from the ad")
    assert fake_transcriptions.call_count == 1

    # Second call must hit the (pipeline-versioned) cache, not call Whisper again.
    result2 = transcript.get_transcript(video_path)
    assert result2.status == "OK"
    assert result2.text == "hello from the ad"
    assert fake_transcriptions.call_count == 1


def test_transcript_cache_key_is_versioned_not_legacy_compatible(tmp_path, monkeypatch):
    """A transcript cached under the OLD (pre-audio-extraction) key must NOT be picked up by
    the new pipeline's cache lookup — otherwise a stale/unverified legacy entry could look
    like a fresh success under the new scheme without ever having gone through it."""
    _patch_paths(monkeypatch, tmp_path)
    from src.cache import build_transcript_cache_key, hash_file, save_cached_transcript

    video_path = tmp_path / "clip.mp4"
    _make_video_with_audio(video_path)

    legacy_key = build_transcript_cache_key(hash_file(video_path), "whisper-1")
    save_cached_transcript(legacy_key, {"text": "legacy text", "status": "OK"})

    cached = transcript.peek_cached_transcript(video_path)
    assert cached is None  # not found under the new pipeline-versioned key
