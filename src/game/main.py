import argparse
import time
import cv2

from .camera import open_camera
from .ui import select_camera_gui
from .pose import PoseEstimator
from .render import draw_circles, put_fps, draw_rocks
from .gameplay import RockManager


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--camera", type=int, help="Camera index to open (if provided, skip selector)")
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

    pose = PoseEstimator(max_people=2)
    rock_mgr = RockManager(width=1280, height=720)

    prev = time.time()
    fps = 0.0

    try:
        while True:
            rock_mgr.maybe_spawn()
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            people = pose.process(frame)
            # Draw detected people and collect head circles for collision checks
            head_circles = []
            for i, circles in enumerate(people[:2]):
                draw_circles(frame, circles, color_shift=(0 if i == 0 else 128))
                for c in circles.get("head", []):
                    head_circles.append((c.x, c.y, c.r))

            # Check head-rock collisions (step 4)
            hits = rock_mgr.handle_head_collisions(head_circles)
            if hits > 0:
                cv2.putText(frame, f"HEAD HIT x{hits}", (60, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (20, 20, 230), 3, cv2.LINE_AA)

            # Collect hand circles and check hand-rock collisions (step 5)
            hand_circles = []
            for circles in people[:2]:
                for c in circles.get("hands", []):
                    hand_circles.append((c.x, c.y, c.r))
            hand_events = rock_mgr.handle_collisions(kind="hands", circles=hand_circles)
            hand_hits = hand_events.get("hits", 0)
            if hand_hits > 0:
                cv2.putText(frame, f"HAND HIT x{hand_hits}", (60, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20, 180, 20), 3, cv2.LINE_AA)

            # Update and draw rocks
            now = time.time()
            dt = now - prev
            prev = now
            rock_mgr.update(max(0.0, min(dt, 0.05)))  # clamp dt for stability
            draw_rocks(frame, rock_mgr.rocks)

            # FPS calc (use smoothed FPS)
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt)
            put_fps(frame, fps)

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # Esc
                break
    finally:
        cap.release()
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass


if __name__ == "__main__":
    main()
