import time
import cv2

from .camera import open_camera
from .ui import select_camera_gui
from .pose import PoseEstimator
from .render import draw_circles, put_fps


def main() -> None:
    # Select camera in full-screen GUI
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

    pose = PoseEstimator()

    prev = time.time()
    fps = 0.0

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            circles = pose.process(frame)
            draw_circles(frame, circles)

            # FPS calc
            now = time.time()
            dt = now - prev
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt)
            prev = now
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
