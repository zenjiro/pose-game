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
            for i, circles in enumerate(people[:2]):
                draw_circles(frame, circles, color_shift=(0 if i == 0 else 128))

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
