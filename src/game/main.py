import argparse
import time
import os
import sys
import math
import numpy as np
import threading

from .profiler import init_profiler, get_profiler

from .camera import open_camera, list_available_cameras
from .pose import PoseEstimator, Circle
from .effects import EffectsManager
from .pipeline import LatestFrame, LatestPose, CameraCaptureThread, PoseInferThread, duplicate_center
from .gameplay import RockManager
from .player import GameState
from .audio import AudioManager

# Optional: PIL for rendering Japanese text
try:
    from PIL import Image, ImageDraw, ImageFont  # type: ignore
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# Try to locate a Japanese-capable font per OS
def find_default_jp_font() -> str | None:
    candidates: list[str] = []
    plat = sys.platform
    if plat.startswith("win"):
        candidates = [
            r"C:\\Windows\\Fonts\\meiryob.ttc",
            r"C:\\Windows\\Fonts\\YuGothB.ttc",
            r"C:\\Windows\\Fonts\\meiryo.ttc",
            r"C:\\Windows\\Fonts\\YuGothM.ttc",
            r"C:\\Windows\\Fonts\\msgothic.ttc",
        ]
    elif plat == "darwin":
        candidates = [
            "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
            "/System/Library/Fonts/Hiragino Sans W6.ttc",
            "/System/Library/Fonts/ヒラギノ角ゴ ProN W6.ttc",
        ]
    else:
        # Linux
        candidates = [
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
            "/usr/share/fonts/opentype/ipafont-mincho/ipam.ttf",
        ]
    for p in candidates:
        try:
            if os.path.isfile(p):
                return p
        except Exception:
            pass
    return None

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--camera", type=int, help="Camera index to open (if provided, skip selector)")
    parser.add_argument("--tasks-model", type=str, default="models/pose_landmarker_lite.task", help="Optional path to MediaPipe Tasks pose landmarker model file for multi-person detection")
    parser.add_argument("-d", "--duplicate", action="store_true", help="Duplicate center region of camera frame to simulate two players (center clip and duplicate).")
    # If not provided, we try to auto-detect a Japanese-capable font per OS
    parser.add_argument("--jp-font", type=str, default=None, help="Path to a TTF/TTC/OTF font that supports Japanese (for title screen text)")
    parser.add_argument("--profile-csv", type=str, default=None, help="Write per-frame timings to CSV (enables profiler)")
    parser.add_argument("--max-seconds", type=float, default=None, help="Exit automatically after N seconds (for profiling)")
    parser.add_argument("--infer-size", type=int, default=None, help="Resize shorter side for pose inference (keep aspect). Results rescaled back.")
    parser.add_argument("--capture-width", type=int, default=None, help="Override camera capture width (default 1280)")
    parser.add_argument("--capture-height", type=int, default=None, help="Override camera capture height (default 720)")
    parser.add_argument("--hud-outline-shader", action="store_true", help="Experimental: use single-pass shader-based outline for HUD text (T8 prototype)")
    args = parser.parse_args()


    # Initialize profiler
    init_profiler(enabled=bool(args.profile_csv), csv_path=args.profile_csv)
    run_start_ts = time.time()

    # Pre-scan available cameras and set up camera cycling list
    avail_infos = list_available_cameras(max_index=5, width=1280, height=720)
    camera_indices = [info.get("index", 0) for info in avail_infos]
    if not camera_indices:
        # Fallback: if probing found nothing, just try index 0
        camera_indices = [0]

    # Determine initial camera index
    if args.camera is not None:
        start_idx = int(args.camera)
        # Ensure the specified index participates in cycling order
        if start_idx not in camera_indices:
            camera_indices = [start_idx] + [i for i in camera_indices if i != start_idx]
    else:
        start_idx = camera_indices[0]

    # Track current position in the cycle list
    try:
        current_cam_pos = camera_indices.index(start_idx)
    except ValueError:
        current_cam_pos = 0
        start_idx = camera_indices[current_cam_pos]

    def open_camera_at(pos: int):
        idx_local = camera_indices[pos % len(camera_indices)]
        cap_local = open_camera(idx_local, width=1280, height=720)
        return idx_local, cap_local

    # Capture size CLI (C): allow overriding capture resolution
    # Defaults to 1280x720 if not set
    parser_capture_width = getattr(args, 'capture_width', None)
    parser_capture_height = getattr(args, 'capture_height', None)

    def open_camera_with_cli(pos: int):
        idx_local = camera_indices[pos % len(camera_indices)]
        w = int(parser_capture_width) if parser_capture_width else 1280
        h = int(parser_capture_height) if parser_capture_height else 720
        cap_local = open_camera(idx_local, width=w, height=h)
        return idx_local, cap_local

    idx, cap = open_camera_with_cli(current_cam_pos)
    if cap is None or not cap.isOpened():
        print(f"Error: Could not open initial camera (index={idx}). Trying other cameras...")
        opened = False
        for shift in range(1, len(camera_indices)):
            try_pos = (current_cam_pos + shift) % len(camera_indices)
            idx_try, cap_try = open_camera_with_cli(try_pos)
            if cap_try is not None and cap_try.isOpened():
                idx, cap = idx_try, cap_try
                current_cam_pos = try_pos
                opened = True
                print(f"Switched to camera index {idx}.")
                break
        if not opened:
            print("Error: Could not open any camera. Exiting.")
            return

    
    pose = PoseEstimator(max_people=2, tasks_model=args.tasks_model)
    audio_mgr = AudioManager()
    rock_mgr = RockManager(width=1280, height=720, audio_manager=audio_mgr)
    game_state = GameState(num_players=2, audio_manager=audio_mgr)
    effects = EffectsManager()
    prof = get_profiler()

    # Threaded pipeline: capture thread + infer thread with latest-only queues
    latest_frame = LatestFrame()
    latest_pose = LatestPose()
    cap_stop_event = threading.Event()
    infer_stop_event = threading.Event()
    cam_thread = CameraCaptureThread(cap, latest_frame, cap_stop_event)
    infer_thread = PoseInferThread(pose, latest_frame, latest_pose, infer_stop_event, infer_size=args.infer_size, duplicate=args.duplicate)
    cam_thread.start()
    infer_thread.start()

    prev = time.time()
    fps = 0.0
    dt = 0.0
    # Track gesture start hold time (raise hand above head)
    gesture_hold_start: float | None = None

    # Arcade rendering path
    import arcade
    import pyglet
    WIDTH, HEIGHT = 1280, 720
    class PoseGameWindow(arcade.Window):
        """Arcade window for the game.

        Notes:
        - Text rendering can crash on some Windows/DirectWrite setups (pyglet IndexError in DWrite backend).
          We wrap text draws in a safe helper and disable text if a failure is detected.
        """
        def __init__(self):
            super().__init__(WIDTH, HEIGHT, "Pose Game (Arcade)", fullscreen=True, update_rate=1/60)
            arcade.set_background_color(arcade.color.BLACK)
            self.players = [{"head": [], "hands": [], "feet": []}, {"head": [], "hands": [], "feet": []}]
            self.cap = cap
            self.pose = pose
            self.audio_mgr = audio_mgr
            self.rock_mgr = rock_mgr
            self.game_state = game_state
            self.effects = effects
            self.args = args
            # Shader-based HUD outline (T8) initialization
            self.hud_shader_ok = False
            if getattr(self.args, 'hud_outline_shader', False):
                try:
                    import array
                    self.ctx  # ensure context exists
                    vs = """#version 330\nin vec2 in_vert; out vec2 v_uv; void main(){ v_uv = in_vert*0.5+0.5; gl_Position = vec4(in_vert,0.0,1.0);}"""
                    fs = """#version 330\nuniform sampler2D u_tex;          \nuniform vec2 u_texel;             // 1 pixel in UV space (1/width, 1/height)\nuniform vec4 u_outline_color;     // outline color\nuniform float u_radius;           // blur radius in pixels\n\nin vec2 v_uv;\nout vec4 f_color;\n\nvoid main(){\n    vec4 base = texture(u_tex, v_uv);\n\n    // If base is opaque, draw the glyph as-is\n    if(base.a > 0.0){\n        f_color = base;\n        return;\n    }\n\n    // Soft outline by searching in multiple directions with distance falloff\n    float maxAlpha = 0.0;\n    int samples = 16; // more samples => smoother, but heavier\n\n    for(int i=0; i<samples; i++){\n        float angle = 6.2831853 * float(i) / float(samples); // 0..2pi\n        vec2 dir = vec2(cos(angle), sin(angle));\n        for(float r=1.0; r<=u_radius; r+=1.0){\n            vec2 offset = dir * r * u_texel;\n            float a = texture(u_tex, v_uv + offset).a;\n            if(a > 0.0){\n                maxAlpha = max(maxAlpha, 1.0 - (r / u_radius));\n                break; // nearest hit in this direction is enough\n            }\n        }\n    }\n\n    if(maxAlpha > 0.0){\n        f_color = vec4(u_outline_color.rgb, u_outline_color.a * maxAlpha);\n    } else {\n        discard;\n    }\n}\n"""
                    self.outline_program = self.ctx.program(vertex_shader=vs, fragment_shader=fs)
                    # Create a color texture and attach to FBO (Arcade GL API)
                    color_tex = self.ctx.texture((WIDTH, HEIGHT), components=4)
                    self.hud_fbo = self.ctx.framebuffer(color_attachments=[color_tex])
                    quad_data = array.array('f', [-1,-1, 1,-1, -1,1, 1,-1, 1,1, -1,1])
                    self.fullscreen_vbo = self.ctx.buffer(data=quad_data.tobytes())
                    # Fallback path: use geometry() descriptor if simple_vertex_array isn't available
                    try:
                        self.fullscreen_vao = self.ctx.simple_vertex_array(self.outline_program, self.fullscreen_vbo, "in_vert")
                    except Exception:
                        from arcade.gl import BufferDescription
                        desc = BufferDescription(self.fullscreen_vbo, '2f', ['in_vert'])
                        self.fullscreen_vao = self.ctx.geometry([desc])
                    self._shader_text_queue: list = []
                    self.hud_shader_ok = True
                except Exception as e:
                    print(f"[WARN] HUD outline shader init failed: {e}")
                    self.hud_shader_ok = False
            # Prefer JP-capable fonts to avoid pyglet DirectWrite issues on Windows
            self.jp_fonts = [
                "Meiryo", "Yu Gothic UI", "Yu Gothic", "MS Gothic",
                "Noto Sans CJK JP", "Noto Sans CJK", "Arial Unicode MS"
            ]
            # Build Arcade font candidates following the sample script guidance:
            # - Prefer family names (tuple of strings)
            # - If a font file path is given, register it via arcade.load_font but still use family names
            # - If a family name is given, prepend it to the candidates
            candidates = list(self.jp_fonts)
            user_font = getattr(self.args, 'jp_font', None)
            try:
                if user_font:
                    if os.path.isfile(user_font):
                        try:
                            arcade.load_font(user_font)
                        except Exception:
                            pass
                        # Keep candidates as family names; do not use the file path directly
                    else:
                        # Treat as a family name hint
                        candidates = [str(user_font)] + candidates
                else:
                    # Also try to register a default JP-capable font file if we can locate it
                    jp_font_path = find_default_jp_font()
                    if jp_font_path and os.path.isfile(jp_font_path):
                        try:
                            arcade.load_font(jp_font_path)
                        except Exception:
                            pass
            except Exception:
                pass
            # Arcade 3.3+ expects a string or a tuple of strings
            self.arcade_font_name = tuple(candidates)
            self.last_frame_bgr = None
            self.last_frame_rgb = None
            # Pipeline references
            self.latest_frame = latest_frame
            self.latest_pose = latest_pose
            self.pipeline_enabled = True
            # Thread references and stop events
            self.cap_stop_event = cap_stop_event
            self.infer_stop_event = infer_stop_event
            self.cam_thread = cam_thread
            self.infer_thread = infer_thread
            self.texture = None
            self.bg_sprite = arcade.Sprite(center_x=WIDTH/2, center_y=HEIGHT/2)
            self.bg_sprite.width = WIDTH
            self.bg_sprite.height = HEIGHT
            self.fps = 0.0
            self._prev = time.time()
            self._cam_fail = 0
            self.prof = get_profiler()
            # Pre-allocate Text objects to avoid per-frame draw_text cost
            self.fps_text = arcade.Text("FPS: 0.0", 12, HEIGHT - 38, arcade.color.WHITE, 14, font_name=self.arcade_font_name)
            # Event messages (head hits / hand hits)
            self.head_msg_text = arcade.Text("", 60, HEIGHT - 110, (230, 20, 20), 32, font_name=self.arcade_font_name)
            self.hand_msg_text = arcade.Text("", 60, HEIGHT - 140, (20, 180, 20), 32, font_name=self.arcade_font_name)
            # Create outline texts for event messages (not for FPS as it changes frequently)
            self.head_msg_outline_texts = [] if self.hud_shader_ok else self._create_outline_texts(self.head_msg_text)
            self.hand_msg_outline_texts = [] if self.hud_shader_ok else self._create_outline_texts(self.hand_msg_text)
            self._head_msg_until = 0.0
            self._hand_msg_until = 0.0
            # Title screen texts (lazy initialized)
            self._title_texts = None
            self._title_outline_texts = None
            # Guard to disable text rendering if pyglet/DirectWrite misbehaves
            self._text_ok = True
            # On Windows, prefer PIL-based text overlay to avoid pyglet DirectWrite issues
            self.use_pil_text = sys.platform.startswith('win')
            # Buffers for transient JP messages when using PIL overlay
            self._head_msg_str = ""
            self._hand_msg_str = ""
            
            # Initialize optimized rendering components (now the only option)
            from .render import RockSpriteList, CircleGeometry
            self.rock_sprite_list = RockSpriteList(HEIGHT)
            self.circle_geometry = CircleGeometry()

        def on_update(self, dt: float):
            nonlocal gesture_hold_start
            now = time.time()
            # Smooth FPS
            if dt > 0:
                self.fps = 0.9 * self.fps + 0.1 * (1.0 / dt)
            # Read camera
            self.prof.start_frame()

            with self.prof.section("camera_read"):
                f, _seq_f, _ts_f = self.latest_frame.get()
                if f is None:
                    return
                frame_bgr = f.copy()
                if self.args.duplicate:
                    frame_bgr = duplicate_center(frame_bgr)
            with self.prof.section("pose_infer"):
                people, _seq_p, _ts_p = self.latest_pose.get()

            # Title/game start/restart gesture logic
            now_g = time.time()
            def any_hand_above_head(people_list):
                try:
                    for p in people_list:
                        head_list = p.get("head", [])
                        hand_list = p.get("hands", [])
                        if not head_list or not hand_list:
                            continue
                        head_c = head_list[0]
                        margin = max(5, int(head_c.r * 0.2))
                        for hc in hand_list:
                            if hc.y < head_c.y - margin:
                                return True
                except Exception:
                    pass
                return False

            if not self.game_state.game_started:
                # Gesture-based start: raise a hand above the head for 2 seconds
                if self._title_texts is None:
                    title = arcade.Text("ポーズゲーム", WIDTH/2, HEIGHT*0.70, (255,255,0), 48, anchor_x="center", font_name=self.arcade_font_name)
                    line1 = arcade.Text("あたまで　いわを　よけよう！", WIDTH/2, HEIGHT*0.55, (255,255,255), 24, anchor_x="center", font_name=self.arcade_font_name)
                    line2 = arcade.Text("あしで　いわを　けって　スコアを　かせごう！", WIDTH/2, HEIGHT*0.48, (255,255,255), 24, anchor_x="center", font_name=self.arcade_font_name)
                    hint = arcade.Text("てを　あげると　スタート", WIDTH/2, HEIGHT*0.38, (100,255,100), 26, anchor_x="center", font_name=self.arcade_font_name)
                    self._title_texts = (title, line1, line2, hint)
                    # Create outline texts for title screen
                    self._title_outline_texts = tuple(self._create_outline_texts(text) for text in self._title_texts)
                
                if any_hand_above_head(people):
                    if gesture_hold_start is None:
                        gesture_hold_start = now_g
                    hold_elapsed = now_g - gesture_hold_start
                    if hold_elapsed >= 2.0:
                        self.game_state.start_game()
                        self.audio_mgr.play_game_start()
                        gesture_hold_start = None
                else:
                    gesture_hold_start = None
            elif self.game_state.game_over:
                # Gesture-based restart
                if any_hand_above_head(people):
                    if gesture_hold_start is None:
                        gesture_hold_start = now_g
                    hold_elapsed = now_g - gesture_hold_start
                    if hold_elapsed >= 2.0:
                        self.game_state.reset()
                        self.rock_mgr.reset()
                        gesture_hold_start = None
                else:
                    gesture_hold_start = None
            else:
                # Active gameplay
                self.rock_mgr.maybe_spawn()

            # Map detected people to players by head X position
            h, w = frame_bgr.shape[:2]
            def _head_x(p: dict) -> int | None:
                hs = p.get("head", [])
                return hs[0].x if hs else None
            players = [ {"head": [], "hands": [], "feet": []}, {"head": [], "hands": [], "feet": []} ]
            self.players = players
            if len(people) >= 2:
                idx_x = [(i, _head_x(p)) for i, p in enumerate(people)]
                with_head = [(i, x) for i, x in idx_x if x is not None]
                if len(with_head) >= 2:
                    with_head.sort(key=lambda t: t[1])
                    left_idx = with_head[0][0]
                    right_idx = with_head[-1][0]
                else:
                    left_idx, right_idx = 0, 1
                players[0] = people[left_idx]
                players[1] = people[right_idx]
            elif len(people) == 1:
                x = _head_x(people[0])
                if x is not None and x < w // 2:
                    players[0] = people[0]
                else:
                    players[1] = people[0]

            # Collision and game logic
            if self.game_state.game_started:
                self.game_state.update()
                remaining_time = self.game_state.get_remaining_time()
                if remaining_time <= 10 and remaining_time > 0:
                    self.audio_mgr.play_hurry_alarm()
                # Head collisions per player
                head_hits_display = []
                for i in range(2):
                    circles = players[i]
                    head_circles = [(c.x, c.y, c.r) for c in circles.get("head", [])]
                    if head_circles:
                        rk, pos = self.rock_mgr.find_first_collision(head_circles)
                        if rk is not None and pos is not None:
                            damage_taken = self.game_state.handle_head_hit(i)
                            if damage_taken:
                                # Mark the rock as hit only when damage is taken
                                rk.hit = True
                                rk.hit_time = time.time()
                                # head message disabled (visual feedback via FX only)
                                self.audio_mgr.play_head_hit()
                                # Spawn red, downward-moving effect at the collision point
                                px, py = pos
                                self.effects.spawn_explosion(
                                    px, py,
                                    base_color=(0, 0, 255),  # BGR red
                                    count=128,  # doubled from 64
                                    life_min=0.5, life_max=1.0,
                                    gravity_min=80.0, gravity_max=180.0,
                                    end_color=(40, 40, 40),
                                    size_min=3.0, size_max=9.0  # 1.5x size (was 2.0-6.0)
                                )
                            else:
                                # Invulnerable: no effect and rock remains
                                pass  # head invulnerable message disabled
                # Head message disabled (visual feedback via FX only)
                # Hands collisions
                hand_circles = []
                for circles in players:
                    for c in circles.get("hands", []):
                        hand_circles.append((c.x, c.y, c.r))
                hand_events = self.rock_mgr.handle_collisions(kind="hands", circles=hand_circles)
                hand_hits = hand_events.get("hits", 0)
                if hand_hits > 0:
                    self.audio_mgr.play_hand_hit()
                    # Hand message disabled (visual feedback via FX only)
                    for (px, py) in hand_events.get("positions", []):
                        self.effects.spawn_explosion(
                            px, py,
                            base_color=(255, 160, 100),
                            count=120,  # doubled from 60
                            life_min=0.5 * (2.0/3.0),
                            life_max=1.0 * (2.0/3.0),
                            gravity_min=60.0, gravity_max=140.0,
                            end_color=(90, 110, 130),
                            size_min=3.0, size_max=9.0  # 1.5x size (was 2.0-6.0)
                        )
                # Feet collisions by player
                for i in range(2):
                    circles = players[i]
                    feet = [(c.x, c.y, c.r) for c in circles.get("feet", [])]
                    if feet:
                        events = self.rock_mgr.handle_collisions(kind="feet", circles=feet)
                        hits = events.get("hits", 0)
                        if hits:
                            self.game_state.handle_foot_hit(i, hits)
                            self.audio_mgr.play_foot_hit()
                            for (px, py) in events.get("positions", []):
                                self.effects.spawn_explosion(
                                    px, py,
                                    base_color=(50, 180, 255),
                                    count=224,  # doubled from 112
                                    size_min=3.0, size_max=9.0  # 1.5x size (was 2.0-6.0)
                                )
            # Update managers
            self.rock_mgr.update(max(0.0, min(dt, 0.05)))
            self.effects.update(max(0.0, min(dt, 0.05)))

            self.last_frame_bgr = frame_bgr


        def on_key_press(self, symbol, modifiers):
            # ESC to quit the Arcade game
            try:
                import arcade as _arcade
                if symbol == _arcade.key.ESCAPE:
                    try:
                        _arcade.exit()
                    except Exception:
                        pass
                    try:
                        self.close()
                    except Exception:
                        pass
                # C to cycle camera (Arcade path)
                elif symbol == _arcade.key.C:
                    try:
                        if not hasattr(self, 'camera_indices'):
                            # Initialize camera cycling state from outer scope
                            self.camera_indices = list(camera_indices)
                            self.current_cam_pos = int(current_cam_pos)
                            self.idx = int(idx)
                            self.open_camera_with_cli = open_camera_with_cli
                        if len(self.camera_indices) <= 1:
                            print("[INFO] Only one camera available; cannot cycle.")
                            return
                        next_pos = (self.current_cam_pos + 1) % len(self.camera_indices)
                        if next_pos == self.current_cam_pos:
                            print("[INFO] No other cameras to switch to.")
                            return
                        prev_pos = self.current_cam_pos
                        prev_idx = self.idx
                        # Stop the capture thread first
                        try:
                            if hasattr(self, 'cap_stop_event') and self.cap_stop_event is not None:
                                self.cap_stop_event.set()
                            if hasattr(self, 'cam_thread') and self.cam_thread is not None:
                                try:
                                    self.cam_thread.join(timeout=1.0)
                                except Exception:
                                    pass
                            if hasattr(self, 'cap_stop_event') and self.cap_stop_event is not None:
                                # Reuse the same event object
                                try:
                                    self.cap_stop_event.clear()
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        # Release current camera to avoid backend lock-ups (e.g., Windows DSHOW)
                        try:
                            if hasattr(self, 'cap') and self.cap is not None:
                                self.cap.release()
                        except Exception:
                            pass
                        time.sleep(0.15)
                        # Open next camera
                        idx_next, cap_next = self.open_camera_with_cli(next_pos)
                        if cap_next is not None and cap_next.isOpened():
                            self.cap = cap_next
                            self.idx = idx_next
                            self.current_cam_pos = next_pos
                            # Restart capture thread with new cap but same LatestFrame and stop event
                            try:
                                self.cam_thread = CameraCaptureThread(self.cap, self.latest_frame, self.cap_stop_event)
                                self.cam_thread.start()
                            except Exception as e:
                                print(f"[WARN] Failed to restart camera thread: {e}")
                            print(f"[INFO] Switched to camera index {self.idx} (position {self.current_cam_pos+1}/{len(self.camera_indices)}).")
                        else:
                            print(f"[WARN] Could not open camera at index {self.camera_indices[next_pos]}. Reverting to {prev_idx}.")
                            # Try to reopen previous camera
                            idx_prev, cap_prev = self.open_camera_with_cli(prev_pos)
                            if cap_prev is not None and cap_prev.isOpened():
                                self.cap = cap_prev
                                self.idx = idx_prev
                                self.current_cam_pos = prev_pos
                                try:
                                    self.cam_thread = CameraCaptureThread(self.cap, self.latest_frame, self.cap_stop_event)
                                    self.cam_thread.start()
                                except Exception as e:
                                    print(f"[ERROR] Failed to restart previous camera thread: {e}")
                            else:
                                print("[ERROR] Failed to reopen previous camera; keeping current state.")
                    except Exception as e:
                        print(f"[ERROR] Camera switch failed (Arcade): {e}")
            except Exception:
                pass

        def _create_outline_texts(self, text_obj, outline_color=(0, 0, 0), outline_width=2):
            """Create outline Text objects for a given text object."""
            if text_obj is None:
                return []
            
            try:
                # Extract properties with sensible fallbacks
                txt = getattr(text_obj, 'text', '')
                x = float(getattr(text_obj, 'x', getattr(text_obj, 'start_x', 0)))
                y = float(getattr(text_obj, 'y', getattr(text_obj, 'start_y', 0)))
                font_size = int(getattr(text_obj, 'font_size', 12))
                width = int(getattr(text_obj, 'width', 0) or 0)
                align = getattr(text_obj, 'align', 'left')
                font_name = getattr(text_obj, 'font_name', getattr(self, 'arcade_font_name', None))
                bold = bool(getattr(text_obj, 'bold', False))
                italic = bool(getattr(text_obj, 'italic', False))
                anchor_x = getattr(text_obj, 'anchor_x', 'left')
                anchor_y = getattr(text_obj, 'anchor_y', 'baseline')
                rotation = float(getattr(text_obj, 'rotation', 0.0))

                outline_texts = []
                # Eight-direction outline for smoother text outlining
                for dx, dy in ((-outline_width, 0), (outline_width, 0), (0, -outline_width), (0, outline_width),
                               (-outline_width, -outline_width), (outline_width, -outline_width), 
                               (-outline_width, outline_width), (outline_width, outline_width)):
                    outline_text = arcade.Text(
                        txt, x + dx, y + dy,
                        outline_color,
                        font_size,
                        width=width,
                        align=align,
                        font_name=font_name,
                        bold=bold,
                        italic=italic,
                        anchor_x=anchor_x,
                        anchor_y=anchor_y,
                        rotation=rotation,
                    )
                    outline_texts.append(outline_text)
                return outline_texts
            except Exception:
                return []

        def _update_outline_texts(self, outline_texts, text_obj, outline_width=2):
            """Update existing outline Text objects with new text and position."""
            if not outline_texts or text_obj is None:
                return
            
            try:
                # Extract properties
                txt = getattr(text_obj, 'text', '')
                x = float(getattr(text_obj, 'x', getattr(text_obj, 'start_x', 0)))
                y = float(getattr(text_obj, 'y', getattr(text_obj, 'start_y', 0)))

                # Update outline text positions and content
                directions = [(-outline_width, 0), (outline_width, 0), (0, -outline_width), (0, outline_width),
                             (-outline_width, -outline_width), (outline_width, -outline_width), 
                             (-outline_width, outline_width), (outline_width, outline_width)]
                
                for i, (dx, dy) in enumerate(directions):
                    if i < len(outline_texts):
                        outline_texts[i].text = txt
                        outline_texts[i].x = x + dx
                        outline_texts[i].y = y + dy
            except Exception:
                pass

        def _draw_text_with_outline(self, text_obj, outline_texts=None, outline_color=(0, 0, 0), outline_width=2):
            """Draw an arcade.Text with a black outline using pre-allocated Text objects."""
            if text_obj is None:
                return
            try:
                # Draw outline texts if provided
                if outline_texts:
                    self._update_outline_texts(outline_texts, text_obj, outline_width)
                    for outline_text in outline_texts:
                        outline_text.draw()
                
                # Draw main text
                text_obj.draw()
            except Exception as e:
                # Fall back to default draw if our manual path fails
                try:
                    text_obj.draw()
                except Exception:
                    raise e

        def _safe_draw_text(self, text_obj, outline_texts=None):
            if not getattr(self, '_text_ok', True):
                return
            try:
                self._draw_text_with_outline(text_obj, outline_texts, outline_color=(0, 0, 0), outline_width=2)
            except Exception as e:
                print(f"[Arcade] Text draw disabled due to error: {e}")
                self._text_ok = False

        def on_draw(self):
            self.clear()
            # Draw background camera frame
            if hasattr(self, 'last_frame_bgr') and self.last_frame_bgr is not None:
                frame_rgb = self.last_frame_bgr[:, :, ::-1] # BGR to RGB
                frame_rgb = np.flipud(frame_rgb)
                if not hasattr(self, 'pg_image') or self.pg_image is None:
                    h, w = frame_rgb.shape[:2]
                    self.pg_image = pyglet.image.ImageData(w, h, 'RGB', frame_rgb.tobytes(), pitch=w * 3)
                else:
                    self.pg_image.set_data('RGB', frame_rgb.shape[1] * 3, frame_rgb.tobytes())

                if getattr(self, 'pg_image', None) is not None:
                    # Blit the latest pyglet image to fill the window
                    with self.prof.section("draw_camera"):
                        self.pg_image.blit(0, 0, width=WIDTH, height=HEIGHT)
            # Draw pose circles using optimized geometry-based rendering
            from .render import draw_circles_arcade_optimized
            try:
                with self.prof.section("draw_pose"):
                    draw_circles_arcade_optimized(self.players[0], HEIGHT, color=(0, 0, 255), geometry_renderer=self.circle_geometry)
                    draw_circles_arcade_optimized(self.players[1], HEIGHT, color=(255, 0, 0), geometry_renderer=self.circle_geometry)
            except Exception:
                pass
            # Draw rocks using SpriteList-based rendering
            with self.prof.section("draw_rocks"):
                self.rock_sprite_list.update_rocks(self.rock_mgr.rocks)
                self.rock_sprite_list.draw()
            with self.prof.section("draw_fx"):
                self.effects.draw(HEIGHT, fps=self.fps)
            # Draw HUD using persistent Text objects (avoid per-frame allocations)
            with self.prof.section("draw_osd"):
                # Ensure Text objects are created once
                if not hasattr(self, 'hud_texts'):  # lazy init
                    # Positions
                    margin = 12
                    # Timer centered at top
                    self.timer_text = arcade.Text("0:00", WIDTH/2, HEIGHT - 46, arcade.color.WHITE, 36, anchor_x="center", font_name=self.arcade_font_name)
                    # P1 left
                    self.p1_score_text = arcade.Text("スコア:　0", margin, HEIGHT - 70, (255, 0, 0), 28, font_name=self.arcade_font_name)
                    self.p1_lives_text = arcade.Text("ライフ:　5", margin, HEIGHT - 100, arcade.color.WHITE, 24, font_name=self.arcade_font_name)
                    # P2 right (right-aligned)
                    self.p2_score_text = arcade.Text("スコア:　0", WIDTH - margin, HEIGHT - 70, (0, 0, 255), 28, anchor_x="right", font_name=self.arcade_font_name)
                    self.p2_lives_text = arcade.Text("ライフ:　5", WIDTH - margin, HEIGHT - 100, arcade.color.WHITE, 24, anchor_x="right", font_name=self.arcade_font_name)
                    # FPS at top-left below timer
                    self.fps_text = arcade.Text("FPS: 0.0", margin, HEIGHT - 38, arcade.color.WHITE, 28, font_name=self.arcade_font_name)
                    self.hud_texts = [
                        self.timer_text,
                        self.p1_score_text, self.p1_lives_text,
                        self.p2_score_text, self.p2_lives_text,
                        self.fps_text,
                    ]
                    # Create outline texts for HUD elements (except FPS which changes frequently)
                    if self.hud_shader_ok:
                        self.hud_outline_texts = [[], [], [], [], [], []]
                    else:
                        self.hud_outline_texts = [
                            self._create_outline_texts(self.timer_text),
                            self._create_outline_texts(self.p1_score_text), 
                            self._create_outline_texts(self.p1_lives_text),
                            self._create_outline_texts(self.p2_score_text), 
                            self._create_outline_texts(self.p2_lives_text),
                            []  # Empty for FPS text
                        ]
                # Update dynamic texts
                # Timer
                if self.game_state.game_started and not self.game_state.game_over:
                    remaining_time = self.game_state.get_remaining_time()
                    display_time = int(max(0, math.ceil(remaining_time)))
                else:
                    display_time = int(self.game_state.time_limit)
                minutes = display_time // 60
                seconds = display_time % 60
                self.timer_text.text = f"{minutes}:{seconds:02d}"
                # Scores/Lives
                p1 = self.game_state.get_player(0)
                p2 = self.game_state.get_player(1)
                self.p1_score_text.text = f"スコア:　{p1.score}"
                self.p1_lives_text.text = "ゲームオーバー" if p1.is_game_over else f"ライフ:　{p1.lives}"
                # Match OpenCV coloring: green normally, red when low lives (<=1), invulnerable, or game over
                self.p1_lives_text.color = (255, 50, 50) if (p1.is_game_over or p1.is_invulnerable() or p1.lives <= 1) else (100, 255, 100)
                self.p2_score_text.text = f"スコア:　{p2.score}"
                self.p2_lives_text.text = "ゲームオーバー" if p2.is_game_over else f"ライフ:　{p2.lives}"
                self.p2_lives_text.color = (255, 50, 50) if (p2.is_game_over or p2.is_invulnerable() or p2.lives <= 1) else (100, 255, 100)
                # FPS
                self.fps_text.text = f"FPS: {self.fps:.1f}"
                # Draw all HUD texts
                if not self.hud_shader_ok:
                    for i, t in enumerate(self.hud_texts):
                        outline_texts = self.hud_outline_texts[i] if i < len(self.hud_outline_texts) else None
                        self._safe_draw_text(t, outline_texts)
            # Draw transient event messages (similar to OpenCV OSD)
            now_t = time.time()
            if self.hud_shader_ok:
                # Shader path: first render HUD-related texts into FBO using normal draw path (no outlines), then composite with outline shader
                try:
                    self.hud_fbo.clear(color=(0, 0, 0, 0))
                    with self.hud_fbo.activate():
                        # Draw base (head/hand messages + title + game over) without outlines
                        if now_t < getattr(self, '_head_msg_until', 0.0) and self.head_msg_text.text:
                            self.head_msg_text.draw()
                        if now_t < getattr(self, '_hand_msg_until', 0.0) and self.hand_msg_text.text:
                            self.hand_msg_text.draw()
                        if not self.game_state.game_started and self._title_texts is not None:
                            for t in self._title_texts:
                                t.draw()
                        if self.game_state.game_over:
                            winner = self.game_state.get_winner()
                            if winner == 0:
                                left_msg = "かち！"; right_msg = "まけ…"
                            elif winner == 1:
                                left_msg = "まけ…"; right_msg = "かち！"
                            else:
                                left_msg = right_msg = "ひきわけ"
                            if not hasattr(self, 'game_over_texts'):
                                self.game_over_texts = {
                                    "left": arcade.Text("", WIDTH / 4, HEIGHT * 0.45, (255, 255, 0), 48, anchor_x="center", font_name=self.arcade_font_name),
                                    "right": arcade.Text("", 3 * WIDTH / 4, HEIGHT * 0.45, (255, 255, 0), 48, anchor_x="center", font_name=self.arcade_font_name),
                                    "restart": arcade.Text("てを　あげると　もういちど", WIDTH / 2, HEIGHT * 0.35, (100, 255, 100), 26, anchor_x="center", font_name=self.arcade_font_name)
                                }
                            self.game_over_texts["left"].text = left_msg
                            self.game_over_texts["right"].text = right_msg
                            self.game_over_texts["left"].draw(); self.game_over_texts["right"].draw(); self.game_over_texts["restart"].draw()
                        # HUD main texts (timer, scores, lives, FPS)
                        if hasattr(self, 'hud_texts'):
                            for t in self.hud_texts:
                                t.draw()
                    # Composite with outline shader: sample alpha neighborhood to create outline
                    tex = self.hud_fbo.color_attachments[0]
                    # Switch back to default framebuffer for compositing
                    try:
                        self.ctx.screen.use()
                    except Exception:
                        pass
                    self.outline_program['u_tex'] = 0
                    self.outline_program['u_texel'] = (1.0/tex.width, 1.0/tex.height)
                    self.outline_program['u_outline_color'] = (0.0,0.0,0.0,1.0)
                    self.outline_program['u_radius'] = 2.0
                    tex.use(0)
                    # Render using VAO if available, otherwise geometry.render(program=...)
                    try:
                        self.fullscreen_vao.render()
                    except Exception:
                        self.fullscreen_vao.render(self.outline_program)
                except Exception as e:
                    if not hasattr(self, '_shader_fail_reported'):
                        print(f"[WARN] HUD shader path failed, falling back: {e}")
                        self._shader_fail_reported = True
                    self.hud_shader_ok = False
            else:
                if now_t < getattr(self, '_head_msg_until', 0.0) and self.head_msg_text.text:
                    self._safe_draw_text(self.head_msg_text, self.head_msg_outline_texts)
                if now_t < getattr(self, '_hand_msg_until', 0.0) and self.hand_msg_text.text:
                    self._safe_draw_text(self.hand_msg_text, self.hand_msg_outline_texts)
                if not self.game_state.game_started and self._title_texts is not None:
                    for i, t in enumerate(self._title_texts):
                        outline_texts = self._title_outline_texts[i] if i < len(self._title_outline_texts) else None
                        self._safe_draw_text(t, outline_texts)
                if self.game_state.game_over:
                    winner = self.game_state.get_winner()
                    if winner == 0:
                        left_msg = "かち！"; right_msg = "まけ…"
                    elif winner == 1:
                        left_msg = "まけ…"; right_msg = "かち！"
                    else:
                        left_msg = right_msg = "ひきわけ"
                    if not hasattr(self, 'game_over_texts'):
                        self.game_over_texts = {
                            "left": arcade.Text("", WIDTH / 4, HEIGHT * 0.45, (255, 255, 0), 48, anchor_x="center", font_name=self.arcade_font_name),
                            "right": arcade.Text("", 3 * WIDTH / 4, HEIGHT * 0.45, (255, 255, 0), 48, anchor_x="center", font_name=self.arcade_font_name),
                            "restart": arcade.Text("てを　あげると　もういちど", WIDTH / 2, HEIGHT * 0.35, (100, 255, 100), 26, anchor_x="center", font_name=self.arcade_font_name)
                        }
                        self.game_over_outline_texts = {
                            "left": self._create_outline_texts(self.game_over_texts["left"]),
                            "right": self._create_outline_texts(self.game_over_texts["right"]),
                            "restart": self._create_outline_texts(self.game_over_texts["restart"])
                        }
                    self.game_over_texts["left"].text = left_msg
                    self.game_over_texts["right"].text = right_msg
                    self._safe_draw_text(self.game_over_texts["left"], self.game_over_outline_texts["left"])
                    self._safe_draw_text(self.game_over_texts["right"], self.game_over_outline_texts["right"])
                    self._safe_draw_text(self.game_over_texts["restart"], self.game_over_outline_texts["restart"])


            self.prof.end_frame({"backend": "arcade"})
            # (Experimental) HUD outline shader path placeholder executed (flag parsed earlier)

    win = PoseGameWindow()
    # Run Arcade loop with optional timed exit
    if args.max_seconds is None:
        arcade.run()
    else:
        import threading as _th
        def stop_after_delay():
            time.sleep(max(0.0, args.max_seconds))
            try:
                arcade.exit()
            except Exception:
                pass
        t = _th.Thread(target=stop_after_delay, daemon=True)
        t.start()
        arcade.run()
    # Stop threads before exiting
    try:
        if infer_stop_event:
            infer_stop_event.set()
        if cap_stop_event:
            cap_stop_event.set()
    except Exception:
        pass
    try:
        # Join any known threads started before window creation
        if 'infer_thread' in locals() and infer_thread is not None:
            infer_thread.join(timeout=1.0)
        if 'cam_thread' in locals() and cam_thread is not None:
            cam_thread.join(timeout=1.0)
        # Also join the latest threads managed by the window (if they were restarted)
        if hasattr(win, 'infer_thread') and getattr(win, 'infer_thread') is not None:
            try:
                win.infer_thread.join(timeout=1.0)
            except Exception:
                pass
        if hasattr(win, 'cam_thread') and getattr(win, 'cam_thread') is not None:
            try:
                win.cam_thread.join(timeout=1.0)
            except Exception:
                pass
    except Exception:
        pass
    return



if __name__ == "__main__":
    main()
