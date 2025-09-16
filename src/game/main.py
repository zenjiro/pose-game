import argparse
import time
import cv2

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
            # Only spawn new rocks if game is still active
            if not game_state.game_over:
                rock_mgr.maybe_spawn()
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

            people = pose.process(frame)
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
            # Draw detected people and collect head circles per player for collision checks
            head_hits_display = []
            for i, circles in enumerate(people[:2]):
                draw_circles(frame, circles, color_shift=(0 if i == 0 else 128))
                
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

            # Collect hand circles and check hand-rock collisions (step 5)
            hand_circles = []
            for circles in people[:2]:
                for c in circles.get("hands", []):
                    hand_circles.append((c.x, c.y, c.r))
            hand_events = rock_mgr.handle_collisions(kind="hands", circles=hand_circles)
            hand_hits = hand_events.get("hits", 0)
            if hand_hits > 0:
                cv2.putText(frame, f"HAND HIT x{hand_hits}", (60, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20, 180, 20), 3, cv2.LINE_AA)

            # Collect foot circles per player and check foot-rock collisions (step 6)
            # Use per-player scoring: foot hit => +1
            for i, circles in enumerate(people[:2]):
                feet = [(c.x, c.y, c.r) for c in circles.get("feet", [])]
                if feet:
                    events = rock_mgr.handle_collisions(kind="feet", circles=feet)
                    hits = events.get("hits", 0)
                    if hits:
                        game_state.handle_foot_hit(i, hits)

            # Update and draw rocks
            now = time.time()
            dt = now - prev
            prev = now
            rock_mgr.update(max(0.0, min(dt, 0.05)))  # clamp dt for stability
            draw_rocks(frame, rock_mgr.rocks)

            # Draw scores and lives for players (top-left, below FPS)
            for i in range(2):
                player = game_state.get_player(i)
                y_pos = 80 + i * 60
                
                # Score
                cv2.putText(frame, f"P{i+1} Score: {player.score}", (12, y_pos), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (220, 220, 220), 2, cv2.LINE_AA)
                
                # Lives with color coding
                lives_color = (50, 50, 255) if player.lives <= 1 else (100, 255, 100)
                if player.is_game_over:
                    lives_text = "GAME OVER"
                    lives_color = (50, 50, 255)
                else:
                    lives_text = f"Lives: {player.lives}"
                    # Flash red if invulnerable
                    if player.is_invulnerable():
                        lives_color = (50, 50, 255)
                
                cv2.putText(frame, lives_text, (12, y_pos + 25), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, lives_color, 2, cv2.LINE_AA)
            
            # Display game over message if game ended
            if game_state.game_over:
                winner = game_state.get_winner()
                if winner is not None:
                    msg = f"PLAYER {winner + 1} WINS!"
                else:
                    msg = "TIE GAME!"
                cv2.putText(frame, msg, (frame.shape[1]//2 - 200, frame.shape[0]//2), 
                           cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 255, 255), 4, cv2.LINE_AA)
                
                # Show restart instructions
                restart_msg = "Press SPACE or ENTER to play again"
                cv2.putText(frame, restart_msg, (frame.shape[1]//2 - 220, frame.shape[0]//2 + 60), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)

            # FPS calc (use smoothed FPS)
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt)
            put_fps(frame, fps)

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # Esc
                break
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
