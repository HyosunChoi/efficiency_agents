import cv2
import numpy as np

from src.frame_extractor import extract_frames


def _make_synthetic_video(path, seconds=4, fps=10, size=64, flip_at_frame=22):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (size, size))
    for i in range(seconds * fps):
        # flip color partway through, away from any fixed candidate timestamp,
        # so the scene-change detector (not the fixed-timestamp list) has to find it
        color = (20, 20, 20) if i < flip_at_frame else (220, 220, 220)
        frame = np.full((size, size, 3), color, dtype=np.uint8)
        writer.write(frame)
    writer.release()


def test_extract_frames_skips_timestamps_beyond_duration_and_finds_scene_change(tmp_path):
    video_path = tmp_path / "clip.mp4"
    _make_synthetic_video(video_path, seconds=4, fps=10, flip_at_frame=22)

    out_dir = tmp_path / "frames"
    frames = extract_frames(video_path, out_dir)

    assert len(frames) > 0
    # candidate timestamp 5s/10s exceed the 4s clip and must be skipped, not fabricated
    assert all(f.timestamp_sec <= 4.01 for f in frames)
    assert any(f.source == "last" for f in frames)
    # the color flip at 2.2s (away from any fixed candidate) should be caught by scene-change detection
    assert any(f.source == "scene_change" for f in frames)
    for f in frames:
        assert f.path.exists()
