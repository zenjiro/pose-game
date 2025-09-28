# Profiling Analysis (2025-09-28)

## Summary
Collected 30s run with `uv run python -m game.main --profile-csv prof.csv --max-seconds 30`.
Analyzer script: `scripts/analyze_profile.py`.

| Metric | Value |
|--------|-------|
| Frames | 1004 |
| Avg frame ms | 29.346 |
| Median frame ms | 27.678 |
| 95th pct frame ms | 35.453 |
| Approx mean FPS | ~34.08 |

## Section Statistics
(share = average section time / average frame time)

| Section     | Avg ms | Median | P95  | Max     | Share % |
|-------------|--------|--------|------|---------|---------|
| camera_read | 0.735  | 0.679  | 1.062| 2.346   | 2.50 |
| pose_infer  | 0.005  | 0.005  | 0.009| 0.037   | 0.02 |
| draw_camera | 2.006  | 1.633  | 3.546| 54.394  | 6.84 |
| draw_pose   | 0.433  | 0.387  | 0.725| 3.186   | 1.48 |
| draw_rocks  | 0.388  | 0.301  | 0.661| 5.078   | 1.32 |
| collide     | 0.000  | 0.000  | 0.000| 0.000   | 0.00 |
| draw_fx     | 0.761  | 0.004  | 5.683| 8.941   | 2.59 |
| sfx         | 0.000  | 0.000  | 0.000| 0.000   | 0.00 |
| draw_osd    | 4.609  | 4.122  | 7.266| 178.263 | 15.71 |
| other       | 20.409 |  —     |  —   |   —     | 69.55 |

Notes:
- `pose_infer` appears tiny here because inference is offloaded to a separate thread—main thread only accounts for negligible bookkeeping.
- `other` dominates (≈70%) indicating large un-instrumented time: game update logic, particle/state updates, event loop wait, thread synchronization.

## Slowest Frames
Top 10 frame durations (ms) with residual (= frame - sum(sections)):

```
Frame   0: 650.69 ms (residual 416.45 ms) - heavy one-time initialization
Frame 107:  78.22 ms (residual 66.94 ms)
Frame 275:  64.59 ms (residual 51.12 ms)
Frame 497:  45.64 ms (residual 31.38 ms)
Frame 152:  45.04 ms (residual 37.31 ms)
Frame 627:  43.04 ms (residual 22.62 ms)
Frame 898:  41.67 ms (residual 28.16 ms)
Frame 457:  40.33 ms (residual 29.66 ms)
Frame 674:  40.17 ms (residual 29.23 ms)
Frame 410:  40.14 ms (residual 28.66 ms)
```

Primary spikes: initialization, occasional OSD bursts, particle / unprofiled update work.

## Bottleneck Assessment
1. Immediate measured cost leader: `draw_osd` (HUD/text rendering) at 15.7%.
2. True dominant cost is hidden in `other` (~70%) — un-instrumented logic or synchronization waits.
3. `draw_camera` (texture upload + flip) is the next measurable chunk (6.8%).
4. `draw_fx` shows high variance (median almost 0 but p95 5.68 ms) indicating intermittent particle update/render spikes.
5. Pose estimation is not visible in this thread due to pipeline threading – good, but means we need separate profiling inside the inference thread if we want end-to-end latency stats.

## Recommended Next Steps
### A. Increase Profiling Resolution
Add new sections around currently opaque regions:
- game_update (GameState / RockManager / gesture logic)
- rocks_update (spawn & movement)
- effects_update (particle system)
- sync_wait_frame / sync_wait_pose (blocking waits on latest_frame / latest_pose)
- hud_update (string changes & layout)

This will break down the 20.4 ms "other" bucket and reveal actionable hotspots.

### B. HUD / draw_osd Optimization
- Reduce outline passes: 8-direction outline -> 4-direction (or shader-based single pass).
- Update dynamic text (scores, timer, FPS) every 2-3 frames or only on value change.
- Cache static title / game-over text to a texture (draw once then blit).
- Throttle FPS text update to 0.1s intervals.
- Consider consolidating multiple Text draws into a single batched texture.

Expected reduction: 4.6 ms → ~2–2.5 ms.

### C. Camera Frame Upload
- Move vertical flip (np.flipud) & BGR→RGB conversion to capture thread.
- Reuse a persistent texture or use PBO for async upload (pyglet raw GL) to cut stalls.
- Avoid reallocating ImageData; ensure pitch stable & no hidden copies.

### D. Particle / Effects Spikes (draw_fx)
- Consolidate particle attributes into NumPy arrays (vectorized updates) or GPU side.
- Impose per-frame particle update cap; defer off-screen cleanup to every N frames.
- Reduce burst particle counts (e.g. 112 -> 48) and shorten lifetimes slightly.

### E. Synchronization Latency
- Replace blocking get() with non-blocking fetch + reuse previous pose if no new data.
- Add timing sections to quantify wait cost inside on_update.

### F. Adaptive Degradation Strategy
When frame_ms > 2 × median:
- Skip HUD update & heavy particle spawns for that frame.
- Defer large text outline redraw.

### G. Inference Thread Profiling
Inside inference thread, record:
- preproc_resize, infer_run, postproc_decode
Write a separate CSV or extend existing rows with async timings (frame id correlation).

### H. Object Allocation Reduction
- Reuse dict/list structures for players & circles each frame.
- Convert frequently accessed dict lookups to local variables or lightweight dataclasses.

## Prioritized Action Plan
1. Add new profiling sections (low effort, high insight).
2. HUD update frequency + outline reduction.
3. Move frame transforms (flip/RGB) to capture thread; confirm draw_camera drop.
4. Vectorize / cap particle system.
5. Add inference-thread detailed timing.
6. Implement adaptive degradation for spikes.

## Estimated Impact (Back-of-envelope)
| Optimization | Est. Saved ms | Resulting Avg Frame (ms) | FPS Approx |
|--------------|---------------|--------------------------|-----------|
| HUD reduction (-2 ms) | 2.0 | 27.3 | 36.6 |
| Camera upload (-0.8 ms) | 0.8 | 26.5 | 37.7 |
| Particle variance (-0.7 ms mean) | 0.7 | 25.8 | 38.8 |
| Object reuse / wait tuning (-0.8 ms) | 0.8 | 25.0 | 40.0 |
| TOTAL (non-overlapping optimistic) | 4.3 | ~25.0 | ~40 FPS |

Coupled with possible inference optimizations (smaller infer size, if quality acceptable) could push toward >40 FPS.

## Conclusion
Current main-thread frame time is dominated by unprofiled logic and HUD rendering. Pose inference is successfully offloaded but now hides its cost from main-thread metrics. The next improvements require (a) exposing hidden time with finer profiling, and (b) reducing predictable overhead from HUD, texture upload, and particle spikes. Following the outlined prioritization should yield a realistic path from ~34 FPS to ~38–40 FPS without major architectural changes.

---
Generated from prof.csv with scripts/analyze_profile.py.
