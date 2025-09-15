from .camera import show_fullscreen_camera, list_available_cameras


def main() -> None:
    # List cameras first and let user choose in console
    candidates = list_available_cameras(max_index=5, width=1280, height=720)
    if not candidates:
        print("No cameras detected. Please connect a camera and try again.")
        return

    print("Available cameras:")
    for i, info in enumerate(candidates):
        res = info.get("resolution") or ("?", "?")
        print(f"  [{i}] device_index={info['index']} backend={info['backend']} resolution={res[0]}x{res[1]}")

    # Ask user to select
    try:
        selection = int(input(f"Select camera [0-{len(candidates)-1}]: ").strip())
    except Exception:
        selection = 0

    if selection < 0 or selection >= len(candidates):
        print("Invalid selection. Using 0.")
        selection = 0

    chosen = candidates[selection]
    idx = int(chosen["index"])  # actual device index

    show_fullscreen_camera(device_index=idx, width=1280, height=720, window_name="Pose Game")


if __name__ == "__main__":
    main()
