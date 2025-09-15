import cv2
from typing import Optional


def open_camera(device_index: int = 0, width: Optional[int] = None, height: Optional[int] = None) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(device_index)

    # Optionally set resolution if provided
    if width is not None:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
    if height is not None:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))

    return cap


def show_fullscreen_camera(device_index: int = 0, width: Optional[int] = None, height: Optional[int] = None, window_name: str = "Pose Game") -> None:
    """
    Open the camera and display frames in a fullscreen window.
    Press Esc to exit.
    """
    cap = open_camera(device_index, width, height)
    if not cap.isOpened():
        print(f"Error: Could not open camera (device_index={device_index}).")
        return

    # Create fullscreen window
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                # If frame read fails, try to continue; break after several failures if needed
                print("Warning: Failed to read frame from camera.")
                break

            # OpenCV uses BGR; for now we display as-is
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
