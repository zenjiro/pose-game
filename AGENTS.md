(The file `d:\kumano\python\pose-game\AGENTS.md` exists, but is empty)
# Agents guide for the pose-game repository

This file is a concise, developer-friendly summary intended for automated coding agents and contributors who will work on this repository.

Repository at-a-glance
- Name: pose-game
- Purpose: Prototype 2D falling-objects game that uses MediaPipe Pose and OpenCV to detect players (head/hands/feet) from a webcam. Local, offline two-player (same camera) gameplay.
- Language: Python 3.10+
- Run with: uv run python -m game.main (see pyproject.toml and README)

Quick facts (collected from source)
- Entrypoint: `src/game/main.py` (module `game.main`) — game loop, camera selection, PoseEstimator, RockManager, draw and input handling.
- Main modules under `src/game/`:
	- `camera.py` — camera opening helpers, fullscreen preview, backend probing.
	- `devices.py` — platform-specific camera name detection (Windows PowerShell helper).
	- `pose.py` — `PoseEstimator` class: prefers MediaPipe Tasks API for multi-person; falls back to Solutions API for single-person. Returns lists of circle groups for `head`, `hands`, `feet`.
	- `entities.py` — dataclasses (e.g., `Rock`).
	- `gameplay.py` — `RockManager` for spawning/updating rocks.
	- `render.py` — drawing helpers (landmarks, FPS, rocks).
	- `ui.py` — camera selection GUI (preview, keyboard navigation).

How to run (developer machine)
1. Python 3.10+ recommended.
2. Install uv (optional but recommended per project): https://docs.astral.sh/uv/
3. Create a venv and install dependencies (or use uv):
	 - uv venv
	 - uv add opencv-python mediapipe numpy
4. Run the game once UI and modules are implemented:
	 - uv run python -m game.main
	 or directly with Python if dependencies and PYTHONPATH align:
	 - python -m game.main

Notes about behavior and current implementation
- Pose detection: `PoseEstimator` will try to use MediaPipe Tasks API (`PoseLandmarker`) when `max_people>1` and Tasks is available; otherwise it uses the single-person Solutions API. It returns structured circle groups for drawing and future collision checks.
- Camera handling: `open_camera()` probes several backends (Windows-friendly order). `ui.select_camera_gui()` provides a fullscreen selector with preview and keyboard controls.
- Game objects: Rocks are spawned by `RockManager` with tunable parameters (`spawn_interval`, speed, radius) and updated each frame.
- Rendering: `draw_circles()` overlays head/hand/foot circles; `draw_rocks()` draws filled circles for rocks.

Coding conventions and expectations for agents
- Keep changes minimal and well-scoped. Follow existing code style (type hints, small functions, docstrings). The repository is small — prefer incremental edits.
- Tests: None exist currently. If adding behavior, include small unit tests for pure logic (e.g., collision calculations) and keep them lightweight.
- Backwards-compatible changes: When modifying `PoseEstimator`, preserve both Tasks and Solutions API support and maintain the `process()` return shape (list of dicts with keys `head`, `hands`, `feet`).

Recommended tasks for a coding agent (examples)
- Implement collision detection and scoring flow:
	- Add a small `collision.py` or extend `gameplay.py` to detect rock vs head/hands/feet collisions.
	- Update `RockManager` or add `GameState` to handle scores, lives, and game states (TITLE/PLAYING/GAME_OVER).
	- Add unit tests for collision math (circle-circle overlap) and score/life updates.
- Add config/constants module (`config.py`) to centralize tunable parameters (spawn rates, radii scale, initial lives, game duration).
- Improve robustness around camera probing on non-Windows systems (devices.py currently implements Windows-only helpers).
- Add a lightweight CLI or `uv` script entry in `pyproject.toml` (if desired) to document run commands.

Developer tips and gotchas
- MediaPipe Tasks API availability is runtime-dependent. Keep fallbacks and avoid hard crashes if Tasks is missing.
- Windows camera names from PowerShell may not map 1:1 to OpenCV indices — treat names as hints only.
- OpenCV's `waitKeyEx` codes vary by platform/keyboard. `ui.py` already contains several fallbacks for arrow keys.
- Keep per-frame work short: Pose inference is the slowest operation; consider throttling or using a separate thread if you add heavier game logic.

Files changed by agent edits should include a brief test or smoke-run verification in the commit message.

Next steps taken for this task
- I created this `AGENTS.md` summary to help automated agents and contributors understand the repository and recommended work.
- Step 7 completed: Implemented life calculation system with initial 3 lives, head hit damage (-1), invulnerability frames, and game over detection.

Requirements coverage
- User asked: initialize `AGENTS.md` for coding agents and create an English summary covering files and how to run — Completed.
- Step 7 from plan.md: Life calculation (initial 3, head hit -1) — Completed.

Recent implementation details for Step 7:
- Added `src/game/player.py` with `PlayerState` and `GameState` classes to manage player lives, scores, and game state
- Implemented invulnerability system (1 second after head hit) to prevent rapid life loss
- Updated main game loop to use per-player head collision detection with life tracking
- Enhanced UI to display both lives and scores with color coding (red when low/invulnerable, green when healthy)
- Added game over detection and winner announcement when a player reaches 0 lives
- Players start with 3 lives, lose 1 life per head hit (respecting invulnerability), and game ends when any player reaches 0 lives

