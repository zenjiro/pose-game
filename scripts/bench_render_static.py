#!/usr/bin/env python3
"""
Bench: Render-only on a fixed frame for OpenCV and Arcade.

Usage examples:
  uv run python scripts/bench_render_static.py --backend arcade --seconds 10 --skip-first 1
  uv run python scripts/bench_render_static.py --backend opencv --seconds 10 --skip-first 1
  uv run python scripts/bench_render_static.py --backend arcade --seconds 10 --optimized --skip-first 1
  uv run python scripts/bench_render_static.py --compare --seconds 10

This script opens the game in the specified backend, but focuses on measuring 
draw_* costs by running realistic game scenarios with fixed camera/pose data.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import os
from pathlib import Path


def run_benchmark(backend: str, seconds: float, skip_first: int, infer_size: int, 
                 legacy: bool = False, duplicate: bool = False) -> str:
    """Run a single benchmark and return the CSV path."""
    
    base_cmd = [
        sys.executable, "-m", "game.main", 
        "--profile", 
        "--max-seconds", f"{seconds}", 
        "--infer-size", f"{infer_size}"
    ]
    
    # Backend selection - currently only Arcade is supported in main.py
    # OpenCV backend would need separate implementation
    if backend == "opencv":
        print("Warning: OpenCV backend not currently supported in main.py. Using Arcade.")
        backend = "arcade"
    
    # Rendering mode flags (optimized is now default)
    if legacy:
        base_cmd.append("--legacy-rendering")
    
    if duplicate:
        base_cmd.append("--duplicate")
    
    # Output CSV
    suffix = f"{'_dup' if duplicate else ''}{'_legacy' if legacy else ''}"
    out_csv = f"runs/{backend}_render_static{suffix}_{int(seconds)}s.csv"
    base_cmd += ["--profile-csv", out_csv]
    
    print("Running:", " ".join(base_cmd))
    result = subprocess.run(base_cmd, check=False)
    
    if result.returncode != 0:
        print(f"Warning: Command exited with code {result.returncode}")
    
    return out_csv


def compare_results(csv_files: list[str], skip_first: int):
    """Compare multiple CSV files using the existing compare script."""
    if len(csv_files) < 2:
        print("Need at least 2 CSV files to compare")
        return
    
    print(f"\nComparing results (skip-first={skip_first}):")
    for i in range(len(csv_files) - 1):
        csv_a = csv_files[i]
        csv_b = csv_files[i + 1]
        
        print(f"\n=== Comparing {csv_a} vs {csv_b} ===")
        
        compare_cmd = [
            sys.executable, "scripts/compare_profiles.py",
            csv_a, csv_b,
            "--skip-first", str(skip_first),
            "--out", "console"
        ]
        
        subprocess.run(compare_cmd, check=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["opencv", "arcade"], default="arcade")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--skip-first", type=int, default=1)
    ap.add_argument("--infer-size", type=int, default=192)
    ap.add_argument("--legacy", action="store_true", 
                   help="Use legacy individual draw calls instead of optimized rendering")
    ap.add_argument("--duplicate", action="store_true", 
                   help="Use duplicate mode (2 players)")
    ap.add_argument("--compare", action="store_true",
                   help="Run A/B comparison between optimized (default) and legacy rendering")
    ap.add_argument("--all-backends", action="store_true",
                   help="Test both OpenCV and Arcade backends")
    args = ap.parse_args()
    
    # Ensure runs directory exists
    Path("runs").mkdir(exist_ok=True)
    
    csv_files = []
    
    if args.compare:
        # Run A/B comparison for the specified backend
        print(f"Running A/B comparison for {args.backend} backend")
        
        # Run optimized version (now default)
        csv_a = run_benchmark(args.backend, args.seconds, args.skip_first, 
                             args.infer_size, legacy=False, duplicate=args.duplicate)
        csv_files.append(csv_a)
        
        # Run legacy version for comparison
        csv_b = run_benchmark(args.backend, args.seconds, args.skip_first, 
                             args.infer_size, legacy=True, duplicate=args.duplicate)
        csv_files.append(csv_b)
        
    elif args.all_backends:
        # Test both backends
        for backend in ["opencv", "arcade"]:
            csv_file = run_benchmark(backend, args.seconds, args.skip_first, 
                                   args.infer_size, legacy=args.legacy, 
                                   duplicate=args.duplicate)
            csv_files.append(csv_file)
    else:
        # Single benchmark run
        csv_file = run_benchmark(args.backend, args.seconds, args.skip_first, 
                               args.infer_size, legacy=args.legacy, 
                               duplicate=args.duplicate)
        csv_files.append(csv_file)
    
    # Compare results if we have multiple files
    if len(csv_files) > 1:
        compare_results(csv_files, args.skip_first)
    
    print("\nDone. CSV files generated:")
    for csv_file in csv_files:
        print(f"  {csv_file}")
    
    # Provide analysis commands
    print("\nFor detailed analysis, run:")
    if len(csv_files) >= 2:
        print(f"  uv run python scripts/compare_profiles.py {csv_files[0]} {csv_files[1]} --skip-first {args.skip_first} --out md")


if __name__ == "__main__":
    main()
