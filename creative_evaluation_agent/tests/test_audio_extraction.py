"""Audio extraction must succeed regardless of the source video's container format (this is
the whole point — .mov previously failed Whisper outright), detect a genuinely silent video
without crashing, and never touch the original video file.
"""
import subprocess

import cv2
import imageio_ffmpeg
import numpy as np

from src import audio_extraction
from src.audio_extraction import extract_audio


def _make_video_with_audio(path, seconds=2, container="mp4"):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"color=c=red:s=64x48:d={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-c:v", "libx264", "-c:a", "aac", "-shortest",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)


def _make_silent_video(path, seconds=2, fps=10):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (64, 48))
    for i in range(seconds * fps):
        writer.write(np.full((48, 64, 3), i % 255, dtype=np.uint8))
    writer.release()


def test_extract_audio_succeeds_regardless_of_container_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_extraction, "AUDIO_STAGING_DIR", tmp_path / "staging")

    # .mov extension specifically — this is the format Whisper rejects outright when sent
    # the raw video; audio extraction must not care about the source container at all.
    video_path = tmp_path / "clip.mov"
    _make_video_with_audio(video_path, seconds=2)
    original_bytes = video_path.read_bytes()

    result = extract_audio(video_path, video_hash="testhash1")

    assert result.status == "OK"
    assert result.audio_path.exists()
    assert result.audio_path.suffix == ".mp3"
    assert result.size_bytes > 0
    assert video_path.read_bytes() == original_bytes  # original video untouched


def test_extract_audio_reuses_staged_file_on_second_call(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_extraction, "AUDIO_STAGING_DIR", tmp_path / "staging")

    video_path = tmp_path / "clip.mp4"
    _make_video_with_audio(video_path, seconds=2)

    first = extract_audio(video_path, video_hash="reuse_test")
    mtime_first = first.audio_path.stat().st_mtime

    second = extract_audio(video_path, video_hash="reuse_test")
    assert second.audio_path == first.audio_path
    assert second.audio_path.stat().st_mtime == mtime_first  # not re-extracted


def test_silent_video_reports_no_audio_stream_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_extraction, "AUDIO_STAGING_DIR", tmp_path / "staging")

    video_path = tmp_path / "silent.mp4"
    _make_silent_video(video_path)

    result = extract_audio(video_path, video_hash="silent_test")

    assert result.status == "NO_AUDIO_STREAM"
    assert result.audio_path is None
