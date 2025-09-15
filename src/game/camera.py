import cv2
from typing import Optional, List, Tuple, Dict


def _available_backends() -> List[Tuple[str, int]]:
    names = ["CAP_DSHOW", "CAP_MSMF", "CAP_ANY"]
    backends: List[Tuple[str, int]] = []
    for n in names:
        v = getattr(cv2, n, None)
        if isinstance(v, int):
            backends.append((n, v))
    return backends


def open_camera(
    device_index: int = 0,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> Optional[cv2.VideoCapture]:
    """
    Try to open the camera using several API backends (Windows-friendly order).
    Returns an opened VideoCapture or None if all attempts fail.
    """
    for backend_name, api_pref in _available_backends():
        try:
            cap = cv2.VideoCapture(device_index, api_pref)
        except TypeError:
            # Fallback for OpenCV builds that don't accept apiPreference parameter
            cap = cv2.VideoCapture(device_index)
        if not cap.isOpened():
            cap.release()
            continue

        # Optionally set resolution if provided
        if width is not None:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
        if height is not None:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))

        # Probe one frame to verify backend actually delivers frames
        ok, _ = cap.read()
        if ok:
            print(f"Camera opened with backend {backend_name} (device_index={device_index}).")
            return cap
        cap.release()

    # Final attempt with OpenCV defaults
    cap = cv2.VideoCapture(device_index)
    if cap.isOpened():
        if width is not None:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
        if height is not None:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
        ok, _ = cap.read()
        if ok:
            print(f"Camera opened with default backend (device_index={device_index}).")
            return cap
        cap.release()

    return None


def probe_camera(device_index: int, width: Optional[int] = None, height: Optional[int] = None) -> Dict:
    """Try to open the specified device and return details if successful."""
    for backend_name, api_pref in _available_backends():
        try:
            cap = cv2.VideoCapture(device_index, api_pref)
        except TypeError:
            cap = cv2.VideoCapture(device_index)
        if not cap.isOpened():
            cap.release()
            continue
        if width is not None:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
        if height is not None:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
        ok, frame = cap.read()
        if ok and frame is not None:
            h, w = frame.shape[:2]
            cap.release()
            return {"index": device_index, "backend": backend_name, "resolution": (w, h)}
        cap.release()
    return {"index": device_index, "backend": None, "resolution": None}


def list_available_cameras(max_index: int = 5, width: Optional[int] = None, height: Optional[int] = None) -> List[Dict]:
    found: List[Dict] = []
    for idx in range(max_index + 1):
        info = probe_camera(idx, width=width, height=height)
        if info.get("backend") is not None:
            found.append(info)
    return found


essc_keycodes = {27}


def show_fullscreen_camera(
    device_index: int = 0,
    width: Optional[int] = None,
    height: Optional[int] = None,
    window_name: str = "Pose Game",
) -> None:
    """
    Open the camera and display frames in a fullscreen window.
    Press Esc to exit.
    """
    cap = open_camera(device_index, width, height)
    if cap is None or not cap.isOpened():
        print(
            f"Error: Could not open camera (device_index={device_index}). "
            "Try a different device index (e.g., 1) or close other apps using the camera."
        )
        return

    # Create fullscreen window
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    consecutive_failures = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                consecutive_failures += 1
                if consecutive_failures > 30:
                    print("Warning: Failed to read frames from camera. Exiting.")
                    break
                continue
            else:
                consecutive_failures = 0

            cv2.imshow(window_name, frame)

            key = cv2.waitKey(1) & 0xFF
            if key in essc_keycodes:
                break
    finally:
        cap.release()
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
