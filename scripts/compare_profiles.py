#!/usr/bin/env python3
"""
Compare two profiler CSV files produced by src/game/profiler.py

Usage:
  python scripts/compare_profiles.py <file_a.csv> <file_b.csv> [--skip-first N] [--out md]

Examples:
  python scripts/compare_profiles.py runs/baseline_arcade_10s.csv runs/arcade_text_10s.csv --skip-first 1

The profiler CSV schema is:
  ts, frame_ms, backend, camera_read, pose_infer, draw_camera, draw_pose, draw_rocks, collide, draw_fx, sfx, draw_osd

This script computes:
  - Count of frames (after skipping)
  - Averages for frame_ms and all sections (ms)
  - FPS (1e3 / avg frame_ms)
  - Share of frame for each section (avg section / avg frame)
  - Deltas between A and B

Notes:
  - We recommend skipping the first frame (--skip-first 1) to avoid initialization outliers.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Dict, List, Tuple


NumericColumns = Tuple[str, ...]


@dataclass
class ProfileStats:
    path: Path
    frames: int
    avg: Dict[str, float]  # average ms per column
    med: Dict[str, float]  # median ms per column
    fps: float             # 1000.0 / avg["frame_ms"]
    share: Dict[str, float]  # avg[section] / avg["frame_ms"]


def load_profile(path: Path, skip_first: int = 0) -> Tuple[List[Dict[str, str]], List[str]]:
    rows: List[Dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        for i, row in enumerate(reader):
            if i < skip_first:
                continue
            rows.append(row)
    return rows, headers


def _collect_numeric(rows: List[Dict[str, str]], headers: List[str]) -> Tuple[NumericColumns, Dict[str, List[float]]]:
    # Known non-numeric fields
    non_numeric = {"ts", "backend"}
    numeric_cols: List[str] = [h for h in headers if h and h not in non_numeric]
    values: Dict[str, List[float]] = {h: [] for h in numeric_cols}
    for row in rows:
        for h in numeric_cols:
            s = row.get(h, "")
            try:
                v = float(s)
            except Exception:
                continue
            values[h].append(v)
    return tuple(numeric_cols), values


def compute_stats(path: Path, skip_first: int = 0) -> ProfileStats:
    rows, headers = load_profile(path, skip_first=skip_first)
    numeric_cols, values = _collect_numeric(rows, headers)
    if not rows:
        raise SystemExit(f"No rows after skipping in: {path}")
    avg: Dict[str, float] = {}
    med: Dict[str, float] = {}
    for h in numeric_cols:
        seq = values.get(h, [])
        avg[h] = mean(seq) if seq else 0.0
        med[h] = median(seq) if seq else 0.0
    frame_ms = avg.get("frame_ms", 0.0)
    fps = (1000.0 / frame_ms) if frame_ms > 0 else 0.0
    share: Dict[str, float] = {}
    for h in numeric_cols:
        if h == "frame_ms":
            continue
        share[h] = (avg[h] / frame_ms) if frame_ms > 0 else 0.0
    return ProfileStats(path=path, frames=len(rows), avg=avg, med=med, fps=fps, share=share)


def _fmt_pct(x: float) -> str:
    return f"{x*100.0:5.1f}%"


def _fmt_ms(x: float) -> str:
    return f"{x:7.2f} ms"


def _fmt_fps(x: float) -> str:
    return f"{x:6.2f} fps"


def render_text(a: ProfileStats, b: ProfileStats) -> str:
    lines: List[str] = []
    lines.append(f"A: {a.path}  frames={a.frames}")
    lines.append(f"B: {b.path}  frames={b.frames}")
    lines.append("")
    lines.append("Overall:")
    lines.append(f"  A frame: {_fmt_ms(a.avg.get('frame_ms', 0))} ({_fmt_fps(a.fps)})  median={_fmt_ms(a.med.get('frame_ms', 0))}")
    lines.append(f"  B frame: {_fmt_ms(b.avg.get('frame_ms', 0))} ({_fmt_fps(b.fps)})  median={_fmt_ms(b.med.get('frame_ms', 0))}")
    d_ms = b.avg.get('frame_ms', 0) - a.avg.get('frame_ms', 0)
    d_fps = b.fps - a.fps
    lines.append(f"  Delta:  {_fmt_ms(d_ms)}  ({_fmt_fps(d_fps)})  -> {'faster' if d_ms < 0 else 'slower' if d_ms > 0 else 'same'}")
    lines.append("")

    # Determine section names from 'a' (all keys except frame_ms)
    section_names = [k for k in a.avg.keys() if k != 'frame_ms']
    # Keep a sensible order if possible
    order_hint = [
        "camera_read","pose_infer","draw_camera","draw_pose","draw_rocks","collide","draw_fx","sfx","draw_osd"
    ]
    section_names = sorted(section_names, key=lambda k: (order_hint.index(k) if k in order_hint else 999, k))

    lines.append("Sections (avg ms) and share of frame:")
    for s in section_names:
        a_ms = a.avg.get(s, 0.0); b_ms = b.avg.get(s, 0.0)
        a_sh = a.share.get(s, 0.0); b_sh = b.share.get(s, 0.0)
        d = b_ms - a_ms
        lines.append(f"  {s:12s}  A={_fmt_ms(a_ms)} ({_fmt_pct(a_sh)})  B={_fmt_ms(b_ms)} ({_fmt_pct(b_sh)})  Δ={_fmt_ms(d)}")

    return "\n".join(lines)


def render_md(a: ProfileStats, b: ProfileStats) -> str:
    # Simple Markdown with a table for sections
    header = ["Metric", "A", "B", "Delta"]
    lines: List[str] = []
    lines.append(f"A: `{a.path}`  frames={a.frames}")
    lines.append(f"B: `{b.path}`  frames={b.frames}")
    lines.append("")
    lines.append("Overall")
    lines.append("")
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|---|---:|---:|---:|")
    d_ms = b.avg.get('frame_ms', 0) - a.avg.get('frame_ms', 0)
    d_fps = b.fps - a.fps
    lines.append(f"| frame_ms | {_fmt_ms(a.avg.get('frame_ms', 0))} | {_fmt_ms(b.avg.get('frame_ms', 0))} | {_fmt_ms(d_ms)} |")
    lines.append(f"| fps | {_fmt_fps(a.fps)} | {_fmt_fps(b.fps)} | {_fmt_fps(d_fps)} |")
    lines.append("")

    section_names = [k for k in a.avg.keys() if k != 'frame_ms']
    order_hint = [
        "camera_read","pose_infer","draw_camera","draw_pose","draw_rocks","collide","draw_fx","sfx","draw_osd"
    ]
    section_names = sorted(section_names, key=lambda k: (order_hint.index(k) if k in order_hint else 999, k))

    lines.append("Sections")
    lines.append("")
    lines.append("| Section | A (ms, %) | B (ms, %) | Δ ms |")
    lines.append("|---|---:|---:|---:|")
    for s in section_names:
        a_ms = a.avg.get(s, 0.0); b_ms = b.avg.get(s, 0.0)
        a_sh = a.share.get(s, 0.0); b_sh = b.share.get(s, 0.0)
        d = b_ms - a_ms
        lines.append(f"| {s} | {_fmt_ms(a_ms)} ({_fmt_pct(a_sh)}) | {_fmt_ms(b_ms)} ({_fmt_pct(b_sh)}) | {_fmt_ms(d)} |")

    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare two profiler CSV files.")
    ap.add_argument("file_a", type=Path)
    ap.add_argument("file_b", type=Path)
    ap.add_argument("--skip-first", type=int, default=0, help="Skip first N frames (warm-up)")
    ap.add_argument("--out", choices=["text", "md"], default="text")
    args = ap.parse_args()

    a = compute_stats(args.file_a, skip_first=args.skip_first)
    b = compute_stats(args.file_b, skip_first=args.skip_first)

    if args.out == "md":
        print(render_md(a, b))
    else:
        print(render_text(a, b))


if __name__ == "__main__":
    main()
