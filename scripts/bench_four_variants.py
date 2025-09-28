#!/usr/bin/env python3
"""
Run four profiling variants of the game and summarize results.

Variants:
  1) OpenCV (no --arcade), no --pipeline
  2) OpenCV (no --arcade), with --pipeline
  3) Arcade (--arcade), no --pipeline
  4) Arcade (--arcade), with --pipeline

Usage examples:
  uv run python scripts/bench_four_variants.py --seconds 20 --skip-first 1
  uv run python scripts/bench_four_variants.py --seconds 20 --skip-first 1 --infer-size 192

Notes:
- Requires a working camera and display on your machine.
- Each run writes CSV to runs/<variant>_<seconds>s.csv
- After runs, a summary is printed with avg frame_ms and FPS per variant.
- You can also use scripts/compare_profiles.py for detailed pairwise comparisons.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Dict, List, Tuple


@dataclass
class Variant:
    name: str
    args: List[str]
    csv_path: Path


def compute_stats(path: Path, skip_first: int = 0) -> Tuple[int, float, float]:
    """Return (frames, avg_frame_ms, fps)."""
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows: List[Dict[str, str]] = []
        for i, row in enumerate(reader):
            if i < skip_first:
                continue
            rows.append(row)
    if not rows:
        return 0, 0.0, 0.0
    frame_ms_vals: List[float] = []
    for r in rows:
        try:
            frame_ms_vals.append(float(r.get("frame_ms", "0") or 0.0))
        except Exception:
            pass
    avg_ms = mean(frame_ms_vals) if frame_ms_vals else 0.0
    fps = (1000.0 / avg_ms) if avg_ms > 0 else 0.0
    return len(rows), avg_ms, fps


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--skip-first", type=int, default=1, help="Skip first N frames when summarizing")
    ap.add_argument("--infer-size", type=int, default=None, help="Optional: downscale shorter side for inference")
    ap.add_argument("--profile-osd", action="store_true", help="Enable on-screen profiler overlay during runs")
    args = ap.parse_args()

    seconds = int(args.seconds)
    runs_dir = Path("runs")
    runs_dir.mkdir(exist_ok=True)

    variants: List[Variant] = []
    def make_variant(name: str, extra: List[str]) -> Variant:
        csv_path = runs_dir / f"{name}_{seconds}s.csv"
        v_args = ["-m", "game.main", "--profile", "--max-seconds", f"{seconds}", "--profile-csv", str(csv_path)]
        if args.infer_size:
            v_args += ["--infer-size", f"{int(args.infer_size)}"]
        if args.profile_osd:
            v_args += ["--profile-osd"]
        v_args += extra
        return Variant(name=name, args=v_args, csv_path=csv_path)

    variants.append(make_variant("opencv_no_pipeline", []))
    variants.append(make_variant("opencv_pipeline", ["--pipeline"]))
    variants.append(make_variant("arcade_no_pipeline", ["--arcade"]))
    variants.append(make_variant("arcade_pipeline", ["--arcade", "--pipeline"]))

    print("== Running 4 variants ==")
    print("Note: Close the Arcade/OpenCV window only after it auto-exits; do not press ESC.")
    for v in variants:
        cmd = [sys.executable] + v.args
        print("\n--- Running:", " ".join(cmd))
        try:
            subprocess.run(cmd, check=False)
        except KeyboardInterrupt:
            print("Interrupted. Continuing to next variant...")
        except Exception as e:
            print(f"[ERROR] Variant {v.name} failed to run: {e}")

    print("\n== Summary (skip-first: %d) ==" % args.skip_first)
    best_name = None
    best_fps = -1.0
    for v in variants:
        frames, avg_ms, fps = compute_stats(v.csv_path, skip_first=args.skip_first)
        print(f"{v.name:18s}  frames={frames:5d}  frame_ms={avg_ms:7.2f}  fps={fps:7.2f}  csv={v.csv_path}")
        if fps > best_fps:
            best_fps = fps
            best_name = v.name
    if best_name is not None:
        print(f"\nFastest: {best_name}  ({best_fps:.2f} fps)")

    print("\nTip: For detailed comparisons, try e.g.\n  uv run python scripts/compare_profiles.py runs/opencv_no_pipeline_%ds.csv runs/opencv_pipeline_%ds.csv --skip-first %d\n  uv run python scripts/compare_profiles.py runs/opencv_no_pipeline_%ds.csv runs/arcade_no_pipeline_%ds.csv --skip-first %d\n" % (seconds, seconds, args.skip_first, seconds, seconds, args.skip_first))


if __name__ == "__main__":
    main()
