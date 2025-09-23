from __future__ import annotations

import csv
import os
import threading
import time
from contextlib import contextmanager
from collections import deque, defaultdict
from typing import Dict, Iterable, Optional


_DEFAULT_SECTIONS: tuple[str, ...] = (
    "camera_read",
    "pose_infer",
    "draw_camera",
    "draw_pose",
    "draw_rocks",
    "collide",
    "draw_fx",
    "sfx",
    "draw_osd",
)


class _SectionTimer:
    def __init__(self, prof: "Profiler", name: str) -> None:
        self.prof = prof
        self.name = name
        self.t0 = 0.0

    def __enter__(self):
        if not self.prof.enabled:
            return self
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self.prof.enabled:
            return False
        dt = (time.perf_counter() - self.t0) * 1000.0  # ms
        self.prof._add_time(self.name, dt)
        return False


class Profiler:
    """Lightweight frame-profiler.

    Usage:
      prof = init_profiler(True, csv_path="profile.csv")
      prof.start_frame()
      with prof.section("pose_infer"):
          ...
      prof.end_frame({"backend": "opencv"})
    """

    def __init__(self, enabled: bool = False, csv_path: Optional[str] = None, avg_window: int = 60) -> None:
        self.enabled = enabled
        self.csv_path = csv_path
        self.avg_window = max(1, int(avg_window))

        self._frame_start_ts: float = 0.0
        self._sections_ms: Dict[str, float] = defaultdict(float)
        self._hist_ms: Dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=self.avg_window))
        self._csv_lock = threading.Lock()
        self._csv_writer = None
        self._csv_file = None
        self._header_written = False

        if csv_path and enabled:
            self._open_csv(csv_path)

    def _open_csv(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        f = open(path, "w", newline="", encoding="utf-8")
        self._csv_file = f
        self._csv_writer = csv.writer(f)
        # Initial header
        header = [
            "ts",
            "frame_ms",
            "backend",
        ] + list(_DEFAULT_SECTIONS)
        self._csv_writer.writerow(header)
        self._header_written = True

    def close(self) -> None:
        if self._csv_file:
            try:
                self._csv_file.close()
            except Exception:
                pass
            self._csv_file = None
            self._csv_writer = None

    def start_frame(self) -> None:
        if not self.enabled:
            return
        self._frame_start_ts = time.perf_counter()
        self._sections_ms.clear()

    def end_frame(self, meta: Optional[Dict[str, object]] = None) -> None:
        if not self.enabled:
            return
        now = time.perf_counter()
        frame_ms = (now - self._frame_start_ts) * 1000.0
        # push to history
        self._hist_ms["frame_total"].append(frame_ms)
        for k, v in self._sections_ms.items():
            self._hist_ms[k].append(v)

        # CSV
        if self._csv_writer is not None:
            with self._csv_lock:
                row = [
                    f"{time.time():.6f}",
                    f"{frame_ms:.3f}",
                    f"{(meta or {}).get('backend', '')}",
                ]
                for name in _DEFAULT_SECTIONS:
                    row.append(f"{self._sections_ms.get(name, 0.0):.3f}")
                self._csv_writer.writerow(row)
                try:
                    self._csv_file.flush()
                except Exception:
                    pass

    def section(self, name: str):
        if not self.enabled:
            return _NullContext()
        return _SectionTimer(self, name)

    def _add_time(self, name: str, ms: float) -> None:
        self._sections_ms[name] += ms

    def get_averages(self) -> Dict[str, float]:
        """Return moving averages over the configured window (ms)."""
        out: Dict[str, float] = {}
        for k, dq in self._hist_ms.items():
            if len(dq) == 0:
                continue
            out[k] = float(sum(dq)) / float(len(dq))
        return out

    def osd_lines(self) -> Iterable[str]:
        """Human-friendly OSD lines for overlay."""
        avg = self.get_averages()
        frame = avg.get("frame_total", 0.0)
        names = list(_DEFAULT_SECTIONS)
        yield f"prof: frame {frame:.1f} ms ({(1000.0/frame if frame>0 else 0):.1f} fps)"
        acc = 0.0
        for n in names:
            ms = avg.get(n, 0.0)
            acc += ms
            pct = (ms / frame * 100.0) if frame > 0 else 0.0
            yield f" - {n}: {ms:.1f} ms ({pct:.0f}%)"
        other = max(0.0, frame - acc)
        if other > 0.1:
            pct = (other / frame * 100.0) if frame > 0 else 0.0
            yield f" - other: {other:.1f} ms ({pct:.0f}%)"


class _NullContext:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False


# --- global singleton helpers ---
_global_prof: Optional[Profiler] = None

def init_profiler(enabled: bool = False, csv_path: Optional[str] = None, avg_window: int = 60) -> Profiler:
    global _global_prof
    _global_prof = Profiler(enabled=enabled, csv_path=csv_path, avg_window=avg_window)
    return _global_prof


def get_profiler() -> Profiler:
    global _global_prof
    if _global_prof is None:
        _global_prof = Profiler(enabled=False)
    return _global_prof
