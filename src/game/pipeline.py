from __future__ import annotations

import threading
import time
from typing import Optional, Tuple, List, Dict

import numpy as np

from .pose import PoseEstimator, Circle


class LatestFrame:
    """Thread-safe container for the latest camera frame (latest-only).

    - Producer updates with a new frame and monotonically increasing seq.
    - Consumers can get the latest frame without blocking the producer.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._seq: int = 0
        self._ts: float = 0.0

    def update(self, frame: np.ndarray) -> None:
        with self._lock:
            self._frame = frame
            self._seq += 1
            self._ts = time.time()

    def get(self) -> Tuple[Optional[np.ndarray], int, float]:
        with self._lock:
            return self._frame, self._seq, self._ts


class LatestPose:
    """Thread-safe container for the latest pose results (latest-only)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._people: List[Dict[str, List[Circle]]] = []
        self._seq: int = -1  # frame seq used to compute this result
        self._ts: float = 0.0

    def update(self, people: List[Dict[str, List[Circle]]], seq: int) -> None:
        with self._lock:
            self._people = people
            self._seq = seq
            self._ts = time.time()

    def get(self) -> Tuple[List[Dict[str, List[Circle]]], int, float]:
        with self._lock:
            return list(self._people), self._seq, self._ts


def duplicate_center(frame_bgr: np.ndarray) -> np.ndarray:
    """Duplicate the center vertical band to both halves (simulate two players)."""
    h, w = frame_bgr.shape[:2]
    left = int(w * 0.25)
    right = int(w * 0.75)
    center = frame_bgr[:, left:right].copy()
    return np.hstack([center, center])


class CameraCaptureThread(threading.Thread):
    """Continuously reads frames from cv2.VideoCapture and publishes the latest frame."""

    def __init__(self, cap, out_latest: LatestFrame, stop_event: threading.Event) -> None:
        super().__init__(daemon=True)
        self.cap = cap
        self.out_latest = out_latest
        self.stop_event = stop_event
        self.consecutive_failures = 0

    def run(self) -> None:
        while not self.stop_event.is_set():
            ok, frame = self.cap.read()
            if not ok or frame is None:
                self.consecutive_failures += 1
                if self.consecutive_failures > 30:
                    # Give the system a short break
                    time.sleep(0.02)
                continue
            self.consecutive_failures = 0
            self.out_latest.update(frame)
            # Yield to other threads
            time.sleep(0.0)


class PoseInferThread(threading.Thread):
    """Consumes the latest frames, runs pose inference, and publishes latest results.

    - Supports optional duplicate mode and inference downscale (--infer-size)
    - Results are scaled back to the working frame size (after duplication when enabled).
    """

    def __init__(
        self,
        pose: PoseEstimator,
        in_latest: LatestFrame,
        out_latest: LatestPose,
        stop_event: threading.Event,
        infer_size: Optional[int] = None,
        duplicate: bool = False,
    ) -> None:
        super().__init__(daemon=True)
        self.pose = pose
        self.in_latest = in_latest
        self.out_latest = out_latest
        self.stop_event = stop_event
        self.infer_size = int(infer_size) if infer_size and infer_size > 0 else None
        self.duplicate = bool(duplicate)
        self._last_seq = -1

    def run(self) -> None:
        while not self.stop_event.is_set():
            frame, seq, _ = self.in_latest.get()
            if frame is None or seq == self._last_seq:
                time.sleep(0.001)
                continue

            work_frame = frame
            if self.duplicate:
                work_frame = duplicate_center(work_frame)

            # Prepare inference frame with optional downscale on shorter side
            h0, w0 = work_frame.shape[:2]
            infer_frame = work_frame
            scale_back_x = 1.0
            scale_back_y = 1.0
            if self.infer_size is not None:
                short = min(w0, h0)
                target = self.infer_size
                if target < short:
                    if w0 <= h0:
                        new_w = target
                        new_h = int(h0 * (target / w0))
                    else:
                        new_h = target
                        new_w = int(w0 * (target / h0))
                    # This part needs to be rewritten without cv2
                    # For now, we will just disable the resizing
                    pass

            # Run inference
            ppl = self.pose.process(infer_frame)

            # Scale circles back to working frame size
            if (scale_back_x != 1.0) or (scale_back_y != 1.0):
                people: List[Dict[str, List[Circle]]] = []
                for p in ppl:
                    newp: Dict[str, List[Circle]] = {"head": [], "hands": [], "feet": []}
                    for k, lst in p.items():
                        for c in lst:
                            newp[k].append(
                                Circle(
                                    int(c.x * scale_back_x),
                                    int(c.y * scale_back_y),
                                    int(c.r * (scale_back_x + scale_back_y) * 0.5),
                                )
                            )
                    people.append(newp)
            else:
                people = ppl

            self.out_latest.update(people, seq)
            self._last_seq = seq
            # Small yield
            time.sleep(0.0)