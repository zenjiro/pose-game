#!/usr/bin/env python3
"""
Bench: Render-only on a fixed frame for OpenCV and Arcade.

Usage examples:
  uv run python scripts/bench_render_static.py --backend arcade --seconds 10 --skip-first 1
  uv run python scripts/bench_render_static.py --backend opencv --seconds 10 --skip-first 1

This script opens the game in the specified backend, but freezes camera input
by reusing the last frame. It runs the update/draw loops to measure draw_* costs
without camera_read/pose_infer noise.
"""
from __future__ import annotations

import argparse
import subprocess
import sys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["opencv", "arcade"], default="arcade")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--skip-first", type=int, default=1)
    ap.add_argument("--infer-size", type=int, default=192)
    args = ap.parse_args()

    base_cmd = [sys.executable, "-m", "game.main", "--profile", "--max-seconds", f"{args.seconds}", "--infer-size", f"{args.infer_size}"]
    if args.backend == "arcade":
        base_cmd.append("--arcade")
    out_csv = f"runs/{args.backend}_render_static_{int(args.seconds)}s.csv"
    base_cmd += ["--profile-csv", out_csv]

    print("Running:", " ".join(base_cmd))
    subprocess.run(base_cmd, check=False)

    # Use compare_profiles if two variants are provided externally.
    print("Done. CSV:", out_csv)


if __name__ == "__main__":
    main()
