from .camera import show_fullscreen_camera
from .ui import select_camera_gui


def main() -> None:
    # Show GUI selector for camera choice (arrow keys + Enter/Space)
    idx = select_camera_gui(max_index=5, width=1280, height=720)
    if idx is None:
        print("Canceled camera selection.")
        return

    show_fullscreen_camera(device_index=idx, width=1280, height=720, window_name="Pose Game")


if __name__ == "__main__":
    main()
