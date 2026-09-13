"""Video representative-frame extraction (spec §6): fixed timestamps + scene-change frames.

No system ffmpeg dependency — uses opencv-python-headless's own video decoder. If a
candidate timestamp exceeds the video duration it is simply skipped (never fabricated).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2

from src.config_loader import get_model_config

logger = logging.getLogger(__name__)


@dataclass
class ExtractedFrame:
    path: Path
    timestamp_sec: float
    source: str  # "fixed" | "scene_change" | "last"


def _read_frame_at(cap: cv2.VideoCapture, timestamp_sec: float):
    cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_sec * 1000)
    ok, frame = cap.read()
    return frame if ok else None


def _histogram(frame) -> "cv2.typing.MatLike":
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    hist = cv2.calcHist([gray], [0], None, [64], [0, 256])
    cv2.normalize(hist, hist)
    return hist


def extract_frames(video_path: Path, out_dir: Path) -> list[ExtractedFrame]:
    cfg = get_model_config()["frame_extraction"]
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.error("영상을 열 수 없습니다: %s", video_path)
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    duration_sec = (frame_count / fps) if fps > 0 else 0

    results: list[ExtractedFrame] = []
    seen_timestamps: list[float] = []

    def _save(frame, ts: float, source: str) -> None:
        filename = f"{video_path.stem}_{source}_{ts:.2f}s.jpg"
        path = out_dir / filename
        cv2.imwrite(str(path), frame)
        results.append(ExtractedFrame(path=path, timestamp_sec=ts, source=source))
        seen_timestamps.append(ts)

    for ts in cfg["candidate_timestamps_sec"]:
        if duration_sec and ts > duration_sec:
            continue  # 영상 길이보다 긴 시점은 추정 없이 생략
        frame = _read_frame_at(cap, ts)
        if frame is not None:
            _save(frame, ts, "fixed")

    if cfg.get("include_last_frame") and duration_sec > 0:
        last_ts = max(duration_sec - (1 / fps if fps else 0.05), 0)
        frame = _read_frame_at(cap, last_ts)
        if frame is not None:
            _save(frame, last_ts, "last")

    # Scene-change detection: sample every ~0.5s, compare histograms of consecutive samples.
    threshold = cfg["scene_change_hist_diff_threshold"]
    max_scene_frames = cfg["max_scene_change_frames"]
    sample_interval = 0.5
    prev_hist = None
    scene_frames_found = 0
    t = 0.0
    while duration_sec and t <= duration_sec and scene_frames_found < max_scene_frames:
        frame = _read_frame_at(cap, t)
        if frame is not None:
            hist = _histogram(frame)
            if prev_hist is not None:
                diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
                too_close = any(abs(t - s) < 0.3 for s in seen_timestamps)
                if diff >= threshold and not too_close:
                    _save(frame, t, "scene_change")
                    scene_frames_found += 1
            prev_hist = hist
        t += sample_interval

    cap.release()
    results.sort(key=lambda r: r.timestamp_sec)
    return results
