import argparse
import time
import os
import sys
import cv2
import numpy as np

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

from .camera import open_camera
from .ui import select_camera_gui
from .pose import PoseEstimator
from .render import draw_circles, put_fps, draw_rocks
from .gameplay import RockManager
from .player import GameState


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--camera", type=int, help="Camera index to open (if provided, skip selector)")
    parser.add_argument("--tasks-model", type=str, default="models/pose_landmarker_lite.task", help="Optional path to MediaPipe Tasks pose landmarker model file for multi-person detection")
    parser.add_argument("-d", "--duplicate", action="store_true", help="Duplicate center region of camera frame to simulate two players (center clip and duplicate).")
    # If not provided, we try to auto-detect a Japanese-capable font per OS
    parser.add_argument("--jp-font", type=str, default=None, help="Path to a TTF/TTC/OTF font that supports Japanese (for title screen text)")
    args = parser.parse_args()

    # Choose camera: use CLI arg if provided, otherwise use GUI selector
    if args.camera is not None:
        idx = int(args.camera)
    else:
        idx = select_camera_gui(max_index=5, width=1280, height=720)
        if idx is None:
            print("Canceled camera selection.")
            return

    cap = open_camera(idx, width=1280, height=720)
    if cap is None or not cap.isOpened():
        print(f"Error: Could not open selected camera (index={idx}).")
        return

    window_name = "Pose Game"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    pose = PoseEstimator(max_people=2, tasks_model=args.tasks_model)
    rock_mgr = RockManager(width=1280, height=720)
    game_state = GameState(num_players=2)

    prev = time.time()
    fps = 0.0

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
                    line1 = "頭で岩を避けよう！"
                    line2 = "足で岩を蹴ってスコアを稼ごう！"
                    hint = "スペース または エンター で開始"
                    # Helper to center text
                    def draw_centered(text: str, y: int, font, color=(255,255,0)):
                        if font is None:
                            return
                        # PIL.ImageDraw in newer versions uses textbbox for metrics
                        try:
                            bbox = draw.textbbox((0, 0), text, font=font)
                            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                        except Exception:
                            # Fallback to legacy textsize if available
                            try:
                                tw, th = draw.textsize(text, font=font)  # type: ignore[attr-defined]
                            except Exception:
                                tw, th = 0, 0
                        x = w//2 - tw//2
                        draw.text((x, y), text, fill=color, font=font)
                    draw_centered(title, int(h*0.30), title_font, (255, 255, 0))
                    draw_centered(line1, int(h*0.45), sub_font, (255, 255, 255))
                    draw_centered(line2, int(h*0.52), sub_font, (255, 255, 255))
                    draw_centered(hint, int(h*0.62), hint_font, (100, 255, 100))
                    frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                else:
                    # Fallback to ASCII text
                    cv2.putText(frame, "POSE GAME", (frame.shape[1]//2 - 150, frame.shape[0]//2 - 100), 
                               cv2.FONT_HERSHEY_SIMPLEX, 3.0, (0, 255, 255), 5, cv2.LINE_AA)
                    cv2.putText(frame, "Avoid rocks with your head!", (frame.shape[1]//2 - 200, frame.shape[0]//2 - 20), 
                               cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2, cv2.LINE_AA)
                    cv2.putText(frame, "Hit rocks with your feet to score!", (frame.shape[1]//2 - 230, frame.shape[0]//2 + 20), 
                               cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2, cv2.LINE_AA)
                    cv2.putText(frame, "Press SPACE or ENTER to start", (frame.shape[1]//2 - 220, frame.shape[0]//2 + 80), 
                               cv2.FONT_HERSHEY_SIMPLEX, 1.0, (100, 255, 100), 2, cv2.LINE_AA)
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
                                head_hits_display.append(f"P{i+1} LIFE LOST!")
                            else:
                                head_hits_display.append(f"P{i+1} INVULNERABLE")

                # Display head hit messages
                for idx, msg in enumerate(head_hits_display):
                    cv2.putText(frame, msg, (60, 60 + idx * 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 230), 3, cv2.LINE_AA)

                # Only run collision detection and game logic when game is active
                # Collect hand circles and check hand-rock collisions (step 5)
                hand_circles = []
                for circles in players:
                    for c in circles.get("hands", []):
                        hand_circles.append((c.x, c.y, c.r))
                hand_events = rock_mgr.handle_collisions(kind="hands", circles=hand_circles)
                hand_hits = hand_events.get("hits", 0)
                if hand_hits > 0:
                    cv2.putText(frame, f"HAND HIT x{hand_hits}", (60, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20, 180, 20), 3, cv2.LINE_AA)

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

                # Update and draw rocks
                rock_mgr.update(max(0.0, min(dt, 0.05)))  # clamp dt for stability
                draw_rocks(frame, rock_mgr.rocks)

                # Draw scores and lives for players (P1 left, P2 right)
                h, w = frame.shape[:2]
                margin = 12
                for i in range(2):
                    player = game_state.get_player(i)
                    # Y positions for this player's lines
                    y_score = 80
                    y_lives = y_score + 25

                    # Colors for text: use player landmark colors for labels
                    P1_COLOR = (0, 0, 255)  # red (BGR)
                    P2_COLOR = (255, 0, 0)  # blue (BGR)
                    name_color = P1_COLOR if i == 0 else P2_COLOR

                    score_text = f"P{i+1} Score: {player.score}"
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
                        cv2.putText(frame, score_text, (margin, y_score), cv2.FONT_HERSHEY_SIMPLEX, 0.7, name_color, 2, cv2.LINE_AA)
                        cv2.putText(frame, lives_text, (margin, y_lives), cv2.FONT_HERSHEY_SIMPLEX, 0.6, lives_color, 2, cv2.LINE_AA)
                    else:
                        # Player 2: right side (right-aligned)
                        (score_w, score_h), _ = cv2.getTextSize(score_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                        (lives_w, lives_h), _ = cv2.getTextSize(lives_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                        cv2.putText(frame, score_text, (w - margin - score_w, y_score), cv2.FONT_HERSHEY_SIMPLEX, 0.7, name_color, 2, cv2.LINE_AA)
                        cv2.putText(frame, lives_text, (w - margin - lives_w, y_lives), cv2.FONT_HERSHEY_SIMPLEX, 0.6, lives_color, 2, cv2.LINE_AA)
                
                # Display game over messages side-by-side
                if game_state.game_over:
                    winner = game_state.get_winner()
                    left_center = (w // 4, h // 2)
                    right_center = (3 * w // 4, h // 2)
                    if winner == 0:
                        left_msg = "PLAYER 1 WINS!"
                        right_msg = "PLAYER 2 LOSES"
                    elif winner == 1:
                        left_msg = "PLAYER 1 LOSES"
                        right_msg = "PLAYER 2 WINS!"
                    else:
                        left_msg = right_msg = "TIE"

                    # Helper to center text at a point
                    def put_centered(text: str, center_x: int, center_y: int, scale: float, color: tuple[int,int,int]):
                        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 4)
                        x = center_x - tw // 2
                        y = center_y + th // 2
                        cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 4, cv2.LINE_AA)

                    put_centered(left_msg, left_center[0], left_center[1], 1.4, (0, 255, 255))
                    put_centered(right_msg, right_center[0], right_center[1], 1.4, (0, 255, 255))

                    # Show restart instructions centered
                    restart_msg = "Press SPACE or ENTER to play again"
                    (rw, rh), _ = cv2.getTextSize(restart_msg, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)
                    rx = w // 2 - rw // 2
                    ry = h // 2 + 60
                    cv2.putText(frame, restart_msg, (rx, ry), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)

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
            elif not game_state.game_started and (key == 32 or key == 13):  # Space (32) or Enter (13)
                # Start game from title screen
                game_state.start_game()
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
