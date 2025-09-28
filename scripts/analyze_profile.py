import csv, statistics, sys, math, os
from collections import defaultdict

"""Simple profiler CSV analyzer.

Usage:
    python scripts/analyze_profile.py [prof.csv]
If no path is given, defaults to ./prof.csv in repo root.
Outputs summary statistics and top slow frames.
"""

def percentile(sorted_list, pct: float):
    if not sorted_list:
        return float('nan')
    k = (len(sorted_list)-1) * pct
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_list[int(k)]
    d0 = sorted_list[f] * (c - k)
    d1 = sorted_list[c] * (k - f)
    return d0 + d1

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'prof.csv'
    if not os.path.isfile(path):
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        rows = list(r)
    if not rows:
        print("No data rows.")
        return
    sections = [c for c in rows[0].keys() if c not in ('ts','frame_ms','backend')]
    frame_ms = []
    sec_vals = {s: [] for s in sections}
    for row in rows:
        try:
            fm = float(row['frame_ms'])
        except (ValueError, KeyError):
            continue
        frame_ms.append(fm)
        for s in sections:
            try:
                sec_vals[s].append(float(row[s]))
            except (ValueError, KeyError):
                sec_vals[s].append(0.0)
    avg_frame = statistics.mean(frame_ms)
    med_frame = statistics.median(frame_ms)
    p95_frame = percentile(sorted(frame_ms), 0.95)
    print("=== Frame Summary ===")
    print(f"Frames:             {len(frame_ms)}")
    print(f"Avg frame (ms):     {avg_frame:.3f}")
    print(f"Median frame (ms):  {med_frame:.3f}")
    print(f"95th pct frame (ms):{p95_frame:.3f}")
    print(f"Approx mean FPS:    {1000.0/avg_frame:.2f}")
    print()
    print("=== Section Stats ===")
    header = f"{'section':12s} {'avg':>8s} {'med':>8s} {'p95':>8s} {'max':>8s} {'share%':>8s}"
    print(header)
    print('-'*len(header))
    total_known = 0.0
    means = {}
    for s in sections:
        arr = sec_vals[s]
        if not arr:
            continue
        arr_sorted = sorted(arr)
        avg = statistics.mean(arr)
        med = statistics.median(arr)
        p95 = percentile(arr_sorted, 0.95)
        mx = max(arr)
        share = (avg / avg_frame * 100.0) if avg_frame > 0 else 0.0
        means[s] = avg
        total_known += avg
        print(f"{s:12s} {avg:8.3f} {med:8.3f} {p95:8.3f} {mx:8.3f} {share:8.2f}")
    other = max(0.0, avg_frame - total_known)
    other_share = other / avg_frame * 100.0 if avg_frame>0 else 0.0
    print(f"{'other':12s} {other:8.3f} {'-':>8s} {'-':>8s} {'-':>8s} {other_share:8.2f}")

    # Top N slow frames
    N = 10
    print()
    print(f"=== Top {N} Slow Frames ===")
    indexed = list(enumerate(frame_ms))
    indexed.sort(key=lambda t: t[1], reverse=True)
    for idx, fm in indexed[:N]:
        row = rows[idx]
        # reconstruct summed known sections
        known_sum = sum(float(row.get(s,0.0)) for s in sections)
        residual = fm - known_sum
        print(f"Frame {idx:5d}: {fm:7.2f} ms  residual/other={residual:5.2f} ms")

    # Identify dominant section by average
    if means:
        dom = max(means.items(), key=lambda t: t[1])
        print('\nDominant avg section:', dom[0], f"{dom[1]:.3f} ms ({dom[1]/avg_frame*100:.1f}% of frame)")

    # Simple recommendations
    print("\n=== Recommendations (heuristic) ===")
    # Sort by share descending
    for s, avg in sorted(means.items(), key=lambda t: t[1], reverse=True):
        share = avg/avg_frame*100
        if share < 3:
            continue
        if s.startswith('draw_osd') or s=='draw_osd':
            print("- draw_osd: Consider reducing text outline passes or update HUD less frequently (e.g., every 2-3 frames).")
        elif s=='draw_camera':
            print("- draw_camera: Upload cost could be cut by reusing a persistent GPU texture / avoid full flip each frame.")
        elif s=='draw_fx':
            print("- draw_fx: Batch particle updates, reduce count, or move heavy color/alpha computations to NumPy / shader.")
        elif s=='draw_rocks':
            print("- draw_rocks: Avoid per-frame sprite recreation; update position only or use a single geometry batch.")
        elif s=='pose_infer':
            print("- pose_infer: Currently very small in on-draw thread (inference likely on worker). Add timing inside infer thread if needed.")
    if other_share > 5:
        print("- 'other' time significant: profile sections not yet instrumented (Python overhead, scheduling, event loop). Add finer-grained timers around game logic & window events.")

if __name__ == '__main__':
    main()
