from .camera import show_fullscreen_camera


def main() -> None:
    # Default device index 0, optional resolution can be provided here if needed
    show_fullscreen_camera(device_index=0, width=1280, height=720, window_name="Pose Game")


if __name__ == "__main__":
    main()
