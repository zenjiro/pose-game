# Agents guide for the pose-game repository

This file is a concise, developer-friendly summary intended for automated coding agents and contributors who will work on this repository.

Repository at-a-glance
- Name: pose-game
- Purpose: Prototype 2D falling-objects game that uses MediaPipe Pose and OpenCV to detect players (head/hands/feet) from a webcam. Local, offline two-player (same camera) gameplay.
- Language: Python 3.10+
- Run with: uv run python -m game.main (see pyproject.toml and README)

Quick facts (collected from source)
- Entrypoint: src/game/main.py (module game.main) — game loop, camera auto-detection and cycling, PoseEstimator, RockManager, draw and input handling.
- Main modules under src/game/:
  - camera.py — camera opening helpers and backend probing; list_available_cameras() to pre-scan devices.
  - devices.py — platform-specific camera name detection (Windows PowerShell helper).
  - pose.py — PoseEstimator: prefers MediaPipe Tasks API for multi-person; falls back to Solutions API for single-person. Returns lists of circle groups for head, hands, feet.
  - entities.py — dataclasses (e.g., Rock).
  - gameplay.py — RockManager for spawning/updating rocks.
  - render.py — drawing helpers (landmarks, FPS, rocks).
  - player.py — PlayerState and GameState (lives, score, timers, game-over).

How to run (developer machine)
1. Python 3.10+ recommended.
2. Install uv (optional but recommended per project): https://docs.astral.sh/uv/
3. Create a venv and install dependencies (or use uv):
   - uv venv
   - uv add opencv-python mediapipe numpy
4. Run the game:
   - uv run python -m game.main
   - optionally pass a Japanese font via --jp-font <path> for JP text rendering

Notes about behavior and current implementation
- Camera handling:
  - On startup, the app probes available cameras via list_available_cameras(). If none are detected, it falls back to index 0.
  - You can specify the initial camera with -c/--camera (e.g., -c 1). This does not change runtime cycling behavior.
  - Press C at any time to cycle to the next camera index; the app releases the current capture and tries the next. If opening fails, it stays on the current camera.
- Pose detection: PoseEstimator will try to use MediaPipe Tasks API (PoseLandmarker) when max_people>1 and Tasks is available; otherwise it uses the single-person Solutions API. It returns structured circle groups for drawing and collision checks.
- Game objects: Rocks are spawned by RockManager with tunable parameters and updated each frame.
  - Defaults: spawn_interval=0.5s, vertical speed=150–250 px/s, horizontal speed=-50..50 px/s, radius=20–40 px
  - Tuning: see README "パラメーター調整" section for where to change values in code.
- Rendering: Arcade is the default backend. Uses optimized geometry for pose circles and SpriteList for rocks. HUD outline text uses a shader + FBO composite by default (auto-fallback to plain text if shader init fails). Legacy OpenCV window rendering has been removed; OpenCV image ops are still used for camera and preprocessing.
- Audio: AudioManager (arcade) plays UI/gameplay sounds (start, hits, countdown, game over, rock drop).

Coding conventions and expectations for agents
- Keep changes minimal and well-scoped. Follow existing code style (type hints, small functions, docstrings). The repository is small — prefer incremental edits.
- Tests: None exist currently. If adding behavior, include small unit tests for pure logic (e.g., collision calculations) and keep them lightweight.
- Backwards-compatible changes: When modifying PoseEstimator, preserve both Tasks and Solutions API support and maintain the process() return shape (list of dicts with keys head, hands, feet).

Recommended tasks for a coding agent (examples)
- Implement/extend collision detection and scoring flow:
  - Add/adjust collision.py or logic in gameplay.py for rock vs head/hands/feet.
  - Update RockManager or GameState to handle scores, lives, and game states (TITLE/PLAYING/GAME_OVER).
  - Add unit tests for collision math (circle-circle overlap) and score/life updates.
- Add config/constants module (config.py) to centralize tunable parameters (spawn rates, speeds, radii, initial lives, game duration) and optionally wire to CLI.
- Improve robustness around camera probing on non-Windows systems (devices.py currently implements Windows-only helpers).
- Add a lightweight CLI or uv script entry in pyproject.toml if desired.

Developer tips and gotchas
- MediaPipe Tasks API availability is runtime-dependent. Keep fallbacks and avoid hard crashes if Tasks is missing.
- Windows camera names from PowerShell may not map 1:1 to OpenCV indices — treat names as hints only.
- Key handling (Arcade): ESC (exit), C/c (camera cycle). Title/start uses gesture (raise hand above head).
- Keep per-frame work short: Pose inference is the slowest operation; consider throttling or using a separate thread if you add heavier game logic.

Requirements coverage and recent implementation
- Lives system: Players start with 3 lives; head hit reduces life by 1 with invulnerability frames; game over when any player reaches 0.
- Audio system: Integrated sounds for start, head/hand/foot hits, hurry alarm, game over, rock drop. Graceful fallback if missing files.
- Camera UI: Removed initial camera selection GUI; replaced with auto-detection and runtime C-key cycling. -c still selects initial camera.

Profiling changes
- CLI flags --profile and --profile-osd were removed.
- Profiler now activates only when --profile-csv <path> is supplied; this writes per-frame timing CSV (sections: camera_read, pose_infer, draw_camera, draw_pose, draw_rocks, collide, draw_fx, sfx, draw_osd, plus frame_ms).
- Any logic relying on args.profile or args.profile_osd should be updated to check args.profile_csv instead.

