import argparse
import time
import os
import sys
import math
import cv2
import numpy as np

from .camera import open_camera, list_available_cameras
from .pose import PoseEstimator
from .render import draw_circles, put_fps, draw_rocks
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

def putText_with_outline(frame, text, pos, font, scale, color, thickness, outline_color=(0,0,0), outline_width=2):
    cv2.putText(frame, text, (pos[0]-outline_width, pos[1]), font, scale, outline_color, thickness, cv2.LINE_AA)
    cv2.putText(frame, text, (pos[0]+outline_width, pos[1]), font, scale, outline_color, thickness, cv2.LINE_AA)
    cv2.putText(frame, text, (pos[0], pos[1]-outline_width), font, scale, outline_color, thickness, cv2.LINE_AA)
    cv2.putText(frame, text, (pos[0], pos[1]+outline_width), font, scale, outline_color, thickness, cv2.LINE_AA)
    cv2.putText(frame, text, pos, font, scale, color, thickness, cv2.LINE_AA)

def draw_text_with_outline(draw, text, pos, font, color, outline_color=(0,0,0), outline_width=2):
    draw.text((pos[0]-outline_width, pos[1]), text, font=font, fill=outline_color)
    draw.text((pos[0]+outline_width, pos[1]), text, font=font, fill=outline_color)
    draw.text((pos[0], pos[1]-outline_width), text, font=font, fill=outline_color)
    draw.text((pos[0], pos[1]+outline_width), text, font=font, fill=outline_color)
    draw.text(pos, text, font=font, fill=color)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--camera", type=int, help="Camera index to open (if provided, skip selector)")
    parser.add_argument("--tasks-model", type=str, default="models/pose_landmarker_lite.task", help="Optional path to MediaPipe Tasks pose landmarker model file for multi-person detection")
    parser.add_argument("-d", "--duplicate", action="store_true", help="Duplicate center region of camera frame to simulate two players (center clip and duplicate).")
    # If not provided, we try to auto-detect a Japanese-capable font per OS
    parser.add_argument("--jp-font", type=str, default=None, help="Path to a TTF/TTC/OTF font that supports Japanese (for title screen text)")
    args = parser.parse_args()

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

    idx, cap = open_camera_at(current_cam_pos)
    if cap is None or not cap.isOpened():
        print(f"Error: Could not open initial camera (index={idx}). Trying other cameras...")
        opened = False
        for shift in range(1, len(camera_indices)):
            try_pos = (current_cam_pos + shift) % len(camera_indices)
            idx_try, cap_try = open_camera_at(try_pos)
            if cap_try is not None and cap_try.isOpened():
                idx, cap = idx_try, cap_try
                current_cam_pos = try_pos
                opened = True
                print(f"Switched to camera index {idx}.")
                break
        if not opened:
            print("Error: Could not open any camera. Exiting.")
            return

    window_name = "Pose Game"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    pose = PoseEstimator(max_people=2, tasks_model=args.tasks_model)
    audio_mgr = AudioManager()
    rock_mgr = RockManager(width=1280, height=720, audio_manager=audio_mgr)
    game_state = GameState(num_players=2, audio_manager=audio_mgr)

    prev = time.time()
    fps = 0.0
    dt = 0.0

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            # If duplicate mode is enabled, clip the center vertical band and duplicate it
            # to create a left/right mirrored-like frame for two-player testing.
            if args.duplicate:
                h, w = frame.shape[:2]
                # Clip the center region: keep middle 50% (from 25% to 75%)
                left = int(w * 0.25)
                right = int(w * 0.75)
                center = frame[:, left:right].copy()
                # Resize center to half-width each side if needed to match original width
                # We'll tile [center | center] to recreate the full width. If center*2 != w,
                # resize each half to w//2 to avoid off-by-one issues.
                half_w = w // 2
                if center.shape[1] != half_w:
                    center = cv2.resize(center, (half_w, h), interpolation=cv2.INTER_LINEAR)
                frame = cv2.hconcat([center, center])

            # Run pose detection on a clean frame BEFORE drawing any UI overlays.
            people = pose.process(frame)

            # Show title screen if game hasn't started
            if not game_state.game_started:
                # Show title screen (draw after detection to avoid occluding pose inputs)
                h, w = frame.shape[:2]
                # Try to render Japanese via PIL if available and font provided
                jp_font_path = args.jp_font
                if jp_font_path is None:
                    jp_font_path = find_default_jp_font()
                if PIL_AVAILABLE and jp_font_path and os.path.isfile(jp_font_path):
                    img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    draw = ImageDraw.Draw(img)
                    try:
                        title_font = ImageFont.truetype(jp_font_path, size=int(h * 0.12))
                        sub_font = ImageFont.truetype(jp_font_path, size=int(h * 0.045))
                        hint_font = ImageFont.truetype(jp_font_path, size=int(h * 0.04))
                    except Exception:
                        title_font = sub_font = hint_font = None
                    # Text content (Japanese)
                    title = "ポーズゲーム"
                    line1 = "あたまで いわを よけよう！"
                    line2 = "あしで いわを けって スコアを かせごう！"
                    hint = "スペース または エンター で スタート"
                    # Helper to center text
                    def draw_centered(text: str, y: int, font, color=(255,255,0)):
                        if font is None:
                            return
                        
                        # Helper to get text size
                        def get_text_size(txt, fnt):
                            try:
                                bbox = draw.textbbox((0, 0), txt, font=fnt)
                                return bbox[2] - bbox[0], bbox[3] - bbox[1]
                            except Exception:
                                try:
                                    return draw.textsize(txt, font=fnt)
                                except Exception:
                                    return 0, 0

                        tw, _ = get_text_size(text, font)
                        x = w//2 - tw//2
                        
                        draw_text_with_outline(draw, text, (x, y), font, color)

                    draw_centered(title, int(h*0.30), title_font, (255, 255, 0))
                    draw_centered(line1, int(h*0.45), sub_font, (255, 255, 255))
                    draw_centered(line2, int(h*0.52), sub_font, (255, 255, 255))
                    draw_centered(hint, int(h*0.62), hint_font, (100, 255, 100))
                    frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                else:
                    # Fallback to ASCII text
                    putText_with_outline(frame, "POSE GAME", (frame.shape[1]//2 - 150, frame.shape[0]//2 - 100), 
                               cv2.FONT_HERSHEY_SIMPLEX, 3.0, (0, 255, 255), 5)
                    putText_with_outline(frame, "Avoid rocks with your head!", (frame.shape[1]//2 - 200, frame.shape[0]//2 - 20), 
                               cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
                    putText_with_outline(frame, "Hit rocks with your feet to score!", (frame.shape[1]//2 - 230, frame.shape[0]//2 + 20), 
                               cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
                    putText_with_outline(frame, "Press SPACE or ENTER to start", (frame.shape[1]//2 - 220, frame.shape[0]//2 + 80), 
                               cv2.FONT_HERSHEY_SIMPLEX, 1.0, (100, 255, 100), 2)
            else:
                # Only spawn new rocks if game is started and still active
                if not game_state.game_over:
                    rock_mgr.maybe_spawn()
            # Debug: log frame size and detected people / circle counts (throttled)
            if int(time.time()) % 3 == 0 and int(time.time() * 10) % 10 == 0:  # Every 3 seconds, once per second
                try:
                    h, w = frame.shape[:2]
                except Exception:
                    h = w = None
                print(f"[DEBUG] frame size: {w}x{h}")
                print(f"[DEBUG] PoseEstimator returned {len(people)} people")
                for pi, circles in enumerate(people[:4]):
                    head_count = len(circles.get("head", []))
                    hands_count = len(circles.get("hands", []))
                    feet_count = len(circles.get("feet", []))
                    print(f"[DEBUG] person[{pi}] head={head_count} hands={hands_count} feet={feet_count}")

            # Map detected people to players by head X position
            h, w = frame.shape[:2]
            def _head_x(p: dict) -> int | None:
                hs = p.get("head", [])
                return hs[0].x if hs else None
            players = [ {"head": [], "hands": [], "feet": []}, {"head": [], "hands": [], "feet": []} ]
            if len(people) >= 2:
                # Prefer two with head landmarks; sort by head X (left->right)
                idx_x = [(i, _head_x(p)) for i, p in enumerate(people)]
                with_head = [(i, x) for i, x in idx_x if x is not None]
                if len(with_head) >= 2:
                    with_head.sort(key=lambda t: t[1])
                    left_idx = with_head[0][0]
                    right_idx = with_head[-1][0]
                else:
                    # Fallback to first two detections
                    left_idx, right_idx = 0, 1
                players[0] = people[left_idx]
                players[1] = people[right_idx]
            elif len(people) == 1:
                x = _head_x(people[0])
                if x is not None and x < w // 2:
                    players[0] = people[0]
                else:
                    players[1] = people[0]
            # Always draw pose landmarks regardless of game state (uniform per-player color)
            P1_COLOR = (0, 0, 255)  # Red (BGR)
            P2_COLOR = (255, 0, 0)  # Blue (BGR)
            draw_circles(frame, players[0], color=P1_COLOR)
            draw_circles(frame, players[1], color=P2_COLOR)

            # Only run collision detection and game logic if game has started
            if game_state.game_started:
                game_state.update()  # Check for time limit

                # Display timer
                remaining_time = game_state.get_remaining_time()
                display_time = math.ceil(remaining_time)
                minutes = int(display_time) // 60
                seconds = int(display_time) % 60
                timer_text = f"{minutes}:{seconds:02d}"
                (tw, th), _ = cv2.getTextSize(timer_text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)
                tx = w // 2 - tw // 2
                ty = 40
                putText_with_outline(frame, timer_text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
                
                # (e) left time is 10 seconds (hurry alarm)
                if remaining_time <= 10 and remaining_time > 0:
                    audio_mgr.play_hurry_alarm()

                # Collect head circles per player for collision checks
                head_hits_display = []
                for i in range(2):
                    circles = players[i]
                    # Check head collisions for this specific player
                    head_circles = [(c.x, c.y, c.r) for c in circles.get("head", [])]
                    if head_circles:
                        hits = rock_mgr.handle_head_collisions(head_circles)
                        if hits > 0:
                            # Try to damage the player (respects invulnerability)
                            damage_taken = game_state.handle_head_hit(i)
                            if damage_taken:
                                head_hits_display.append("LIFE LOST!")
                                audio_mgr.play_head_hit()  # (b) hit a rock on the head (bad)
                            else:
                                head_hits_display.append("INVULNERABLE")

                # Display head hit messages
                for idx, msg in enumerate(head_hits_display):
                    putText_with_outline(frame, msg, (60, 60 + idx * 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 230), 3)

                # Only run collision detection and game logic when game is active
                # Collect hand circles and check hand-rock collisions (step 5)
                hand_circles = []
                for circles in players:
                    for c in circles.get("hands", []):
                        hand_circles.append((c.x, c.y, c.r))
                hand_events = rock_mgr.handle_collisions(kind="hands", circles=hand_circles)
                hand_hits = hand_events.get("hits", 0)
                if hand_hits > 0:
                    putText_with_outline(frame, f"HAND HIT x{hand_hits}", (60, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20, 180, 20), 3)
                    audio_mgr.play_hand_hit()  # (c) hit a rock on the hands (a bit good)

                # Collect foot circles per player and check foot-rock collisions (step 6)
                # Use per-player scoring: foot hit => +1
                for i in range(2):
                    circles = players[i]
                    feet = [(c.x, c.y, c.r) for c in circles.get("feet", [])]
                    if feet:
                        events = rock_mgr.handle_collisions(kind="feet", circles=feet)
                        hits = events.get("hits", 0)
                        if hits:
                            game_state.handle_foot_hit(i, hits)
                            audio_mgr.play_foot_hit()  # (d) hit a rock on the foots (very good)

                # Update and draw rocks
                rock_mgr.update(max(0.0, min(dt, 0.05)))  # clamp dt for stability
                draw_rocks(frame, rock_mgr.rocks)

                # Draw scores and lives for players (P1 left, P2 right)
                h, w = frame.shape[:2]
                margin = 12

                jp_font_path = args.jp_font
                if jp_font_path is None:
                    jp_font_path = find_default_jp_font()
                use_jp_font = PIL_AVAILABLE and jp_font_path and os.path.isfile(jp_font_path)

                img_pil = None
                draw = None
                score_font = None
                lives_font = None

                if use_jp_font:
                    img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    draw = ImageDraw.Draw(img_pil)
                    try:
                        score_font = ImageFont.truetype(jp_font_path, size=int(h * 0.04))
                        lives_font = ImageFont.truetype(jp_font_path, size=int(h * 0.035))
                    except Exception:
                        use_jp_font = False # Fallback to ASCII if font loading fails
                
                for i in range(2):
                    player = game_state.get_player(i)
                    # Y positions for this player's lines
                    y_score = 80
                    y_lives = y_score + 30

                    # Colors for text: use player landmark colors for labels
                    P1_COLOR = (0, 0, 255)  # red (BGR)
                    P2_COLOR = (255, 0, 0)  # blue (BGR)
                    name_color = P1_COLOR if i == 0 else P2_COLOR
                    
                    if use_jp_font and draw and score_font and lives_font:
                        score_text = f"スコア: {player.score}"
                        lives_color = (50, 50, 255) if player.lives <= 1 else (100, 255, 100)
                        if player.is_game_over:
                            lives_text = "ゲームオーバー"
                            lives_color = (50, 50, 255)
                        else:
                            lives_text = f"ライフ: {player.lives}"
                            if player.is_invulnerable():
                                lives_color = (50, 50, 255)
                        
                        # PIL uses RGB for color
                        name_color_pil = (name_color[2], name_color[1], name_color[0])
                        lives_color_pil = (lives_color[0], lives_color[1], lives_color[2])

                        if i == 0:
                            # Player 1: left side
                            draw_text_with_outline(draw, score_text, (margin, y_score), score_font, name_color_pil)
                            draw_text_with_outline(draw, lives_text, (margin, y_lives), lives_font, lives_color_pil)
                        else:
                            # Player 2: right side (right-aligned)
                            try:
                                bbox = draw.textbbox((0, 0), score_text, font=score_font)
                                score_w = bbox[2] - bbox[0]
                            except Exception:
                                score_w = 100 # fallback
                            try:
                                bbox = draw.textbbox((0, 0), lives_text, font=lives_font)
                                lives_w = bbox[2] - bbox[0]
                            except Exception:
                                lives_w = 100 # fallback

                            draw_text_with_outline(draw, score_text, (w - margin - score_w, y_score), score_font, name_color_pil)
                            draw_text_with_outline(draw, lives_text, (w - margin - lives_w, y_lives), lives_font, lives_color_pil)

                    else: # Fallback to ASCII
                        score_text = f"Score: {player.score}"
                        lives_color = (50, 50, 255) if player.lives <= 1 else (100, 255, 100)
                        if player.is_game_over:
                            lives_text = "GAME OVER"
                            lives_color = (50, 50, 255)
                        else:
                            lives_text = f"Lives: {player.lives}"
                            if player.is_invulnerable():
                                lives_color = (50, 50, 255)

                        if i == 0:
                            # Player 1: left side
                            putText_with_outline(frame, score_text, (margin, y_score), cv2.FONT_HERSHEY_SIMPLEX, 0.7, name_color, 2)
                            putText_with_outline(frame, lives_text, (margin, y_lives), cv2.FONT_HERSHEY_SIMPLEX, 0.6, lives_color, 2)
                        else:
                            # Player 2: right side (right-aligned)
                            (score_w, _), _ = cv2.getTextSize(score_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                            (lives_w, _), _ = cv2.getTextSize(lives_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                            putText_with_outline(frame, score_text, (w - margin - score_w, y_score), cv2.FONT_HERSHEY_SIMPLEX, 0.7, name_color, 2)
                            putText_with_outline(frame, lives_text, (w - margin - lives_w, y_lives), cv2.FONT_HERSHEY_SIMPLEX, 0.6, lives_color, 2)

                if use_jp_font and img_pil:
                    frame = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
                
                # Display game over messages side-by-side
                if game_state.game_over:
                    winner = game_state.get_winner()
                    # Try to render Japanese via PIL if available and font provided
                    jp_font_path = args.jp_font
                    if jp_font_path is None:
                        jp_font_path = find_default_jp_font()

                    if PIL_AVAILABLE and jp_font_path and os.path.isfile(jp_font_path):
                        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                        draw = ImageDraw.Draw(img)
                        try:
                            msg_font = ImageFont.truetype(jp_font_path, size=int(h * 0.08))
                            restart_font = ImageFont.truetype(jp_font_path, size=int(h * 0.04))
                        except Exception:
                            msg_font = restart_font = None

                        if winner == 0:
                            left_msg = "かち！"
                            right_msg = "まけ…"
                        elif winner == 1:
                            left_msg = "まけ…"
                            right_msg = "かち！"
                        else:
                            left_msg = "ひきわけ"
                            right_msg = "ひきわけ"
                        
                        restart_msg = "スペースキーかエンターキーでもういちど"

                        def draw_centered_gameover(text: str, center_x: int, y: int, font, color=(255,255,0)):
                            if font is None:
                                return
                            try:
                                bbox = draw.textbbox((0, 0), text, font=font)
                                tw, _h = bbox[2] - bbox[0], bbox[3] - bbox[1]
                            except Exception:
                                try:
                                    tw, _h = draw.textsize(text, font=font)
                                except Exception:
                                    tw, _h = 0, 0
                            x = center_x - tw//2
                            draw_text_with_outline(draw, text, (x, y), font, color)

                        y_pos = int(h*0.45)
                        draw_centered_gameover(left_msg, w // 4, y_pos, msg_font)
                        if right_msg:
                            draw_centered_gameover(right_msg, 3 * w // 4, y_pos, msg_font)

                        # Centered restart message
                        draw_centered_gameover(restart_msg, w // 2, int(h*0.62), restart_font, (100, 255, 100))
                        
                        frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                    else:
                        # Fallback to ASCII
                        left_center = (w // 4, h // 2)
                        right_center = (3 * w // 4, h // 2)
                        if winner == 0:
                            left_msg = "WIN!"
                            right_msg = "LOSE"
                        elif winner == 1:
                            left_msg = "LOSE"
                            right_msg = "WIN!"
                        else:
                            left_msg = right_msg = "TIE"

                        # Helper to center text at a point
                        def put_centered(text: str, center_x: int, center_y: int, scale: float, color: tuple[int,int,int]):
                            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 4)
                            x = center_x - tw // 2
                            y = center_y + th // 2
                            putText_with_outline(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 4)

                        put_centered(left_msg, left_center[0], left_center[1], 1.4, (0, 255, 255))
                        put_centered(right_msg, right_center[0], right_center[1], 1.4, (0, 255, 255))

                        # Show restart instructions centered
                        restart_msg = "Press SPACE or ENTER to play again"
                        (rw, rh), _ = cv2.getTextSize(restart_msg, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)
                        rx = w // 2 - rw // 2
                        ry = h // 2 + 60
                        putText_with_outline(frame, restart_msg, (rx, ry), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

            # FPS calc (use smoothed FPS) - calculate timing outside game logic
            now = time.time()
            dt = now - prev
            prev = now
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt)
            put_fps(frame, fps)

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # Esc
                break
            elif key in (ord('c'), ord('C')):
                # Cycle to the next camera
                try:
                    if len(camera_indices) <= 1:
                        print("[INFO] Only one camera available; cannot cycle.")
                    else:
                        next_pos = (current_cam_pos + 1) % len(camera_indices)
                        if next_pos == current_cam_pos:
                            print("[INFO] No other cameras to switch to.")
                        else:
                            prev_pos = current_cam_pos
                            prev_idx = idx
                            # Release current camera first to avoid backend lock-ups (e.g., Windows DSHOW)
                            try:
                                cap.release()
                            except Exception:
                                pass
                            # Small delay to let OS release the device
                            time.sleep(0.15)

                            idx_next, cap_next = open_camera_at(next_pos)
                            if cap_next is not None and cap_next.isOpened():
                                cap = cap_next
                                idx = idx_next
                                current_cam_pos = next_pos
                                print(f"[INFO] Switched to camera index {idx} (position {current_cam_pos+1}/{len(camera_indices)}).")
                            else:
                                print(f"[WARN] Could not open camera at index {camera_indices[next_pos]}. Reverting to {prev_idx}.")
                                # Try to reopen previous camera
                                idx_prev, cap_prev = open_camera_at(prev_pos)
                                if cap_prev is not None and cap_prev.isOpened():
                                    cap = cap_prev
                                    idx = idx_prev
                                    current_cam_pos = prev_pos
                                else:
                                    print("[ERROR] Failed to reopen previous camera; exiting.")
                                    break
                except Exception as e:
                    print(f"[ERROR] Camera switch failed: {e}")
            elif not game_state.game_started and (key == 32 or key == 13):  # Space (32) or Enter (13)
                # Start game from title screen
                game_state.start_game()
                audio_mgr.play_game_start()  # (a) start new game
                print("[INFO] Game started!")
            elif game_state.game_over and (key == 32 or key == 13):  # Space (32) or Enter (13)
                # Reset game state for new game
                game_state.reset()
                rock_mgr.reset()
                print("[INFO] Game restarted - all players reset to 3 lives and 0 score")
    finally:
        cap.release()
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass


if __name__ == "__main__":
    main()