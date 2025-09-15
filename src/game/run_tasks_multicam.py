from __future__ import annotations

import os
import time
from typing import Optional

import cv2
import numpy as np
import mediapipe as mp
_ = mp
try:
    # Tasks API
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
    TASKS_AVAILABLE = True
except Exception:
    TASKS_AVAILABLE = False

# We'll draw landmarks directly with OpenCV using normalized coordinates returned by
# the Tasks API. This avoids depending on protobuf classes or mediapipe.solutions
# drawing utilities which can confuse static analyzers in some environments.



def draw_landmarks_on_image(rgb_image: np.ndarray, detection_result) -> np.ndarray:
    pose_landmarks_list = getattr(detection_result, 'pose_landmarks', None)
    annotated_image = np.copy(rgb_image)
    if not pose_landmarks_list:
        return annotated_image

    h, w = annotated_image.shape[:2]

    # Draw normalized landmarks as small circles. pose_landmarks is an iterable of
    # landmark objects with .x and .y in [0,1]. We draw each landmark and a bounding
    # circle per detected person for visibility.
    for pose_landmarks in pose_landmarks_list:
        xs = []
        ys = []
        for lm in pose_landmarks:
            if lm.x is None or lm.y is None:
                continue
            px = int(np.clip(lm.x * w, 0, w - 1))
            py = int(np.clip(lm.y * h, 0, h - 1))
            xs.append(px)
            ys.append(py)
            cv2.circle(annotated_image, (px, py), 3, (0, 255, 0), -1)

        # Draw a simple bounding circle around the person if we have points
        if xs and ys:
            cx = int(sum(xs) / len(xs))
            cy = int(sum(ys) / len(ys))
            rr = int(max(20, 0.25 * (max(xs) - min(xs) if len(xs) > 1 else 40)))
            cv2.circle(annotated_image, (cx, cy), rr, (255, 0, 0), 2)

    return annotated_image


def center_crop(img: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
    h, w = img.shape[:2]
    cx, cy = w // 2, h // 2
    half_w, half_h = target_w // 2, target_h // 2
    x1 = max(0, cx - half_w)
    y1 = max(0, cy - half_h)
    x2 = min(w, cx + half_w)
    y2 = min(h, cy + half_h)
    crop = img[y1:y2, x1:x2]
    # If cropping near edges produced smaller size, pad to target
    if crop.shape[1] != target_w or crop.shape[0] != target_h:
        crop = cv2.copyMakeBorder(
            crop,
            top=0,
            bottom=target_h - crop.shape[0],
            left=0,
            right=target_w - crop.shape[1],
            borderType=cv2.BORDER_CONSTANT,
            value=[0, 0, 0],
        )
    return crop


def build_side_by_side_two_person(frame: np.ndarray, person_w: int, person_h: int) -> np.ndarray:
    # center-crop single frame, then duplicate left-right to create two-person canvas
    crop = center_crop(frame, person_w, person_h)
    left = crop.copy()
    right = crop.copy()
    combined = np.concatenate([left, right], axis=1)
    return combined


def main(model_path: Optional[str] = None, camera_index: int = 0):
    if not TASKS_AVAILABLE:
        print("MediaPipe Tasks API not available in this environment.")
        return

    if model_path is None:
        # Allow environment override
        model_path = os.environ.get("MP_POSE_MODEL", "pose_landmarker_heavy.task")

    use_builtin = False
    if model_path is None or not os.path.exists(model_path):
        print(f"Model file not found: {model_path}. Will attempt to use built-in model if available.")
        use_builtin = True

    # Options
    BaseOptions = mp_python.BaseOptions
    PoseLandmarkerOptions = mp_vision.PoseLandmarkerOptions
    VisionRunningMode = mp_vision.RunningMode

    base_opts = BaseOptions(model_asset_path=None if use_builtin else model_path)
    # Some versions of the Tasks API don't accept min_pose_tracking_confidence.
    try:
        options = PoseLandmarkerOptions(
            base_options=base_opts,
            running_mode=VisionRunningMode.VIDEO,
            num_poses=2,
            min_pose_detection_confidence=0.5,
            min_pose_tracking_confidence=0.5,
        )
    except TypeError:
        options = PoseLandmarkerOptions(
            base_options=base_opts,
            running_mode=VisionRunningMode.VIDEO,
            num_poses=2,
            min_pose_detection_confidence=0.5,
        )

    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"Unable to open camera index {camera_index}")
        return

    # Decide person crop size based on camera resolution (use 1/2 width each)
    ret, frame = cap.read()
    if not ret:
        print("Unable to read from camera")
        cap.release()
        return

    h, w = frame.shape[:2]
    # We'll make two persons side-by-side, so person_w is half of final width.
    person_w = min(480, w // 2)
    person_h = min(640, h)

    # Try to create a Tasks PoseLandmarker. If that fails (no model, built-in model
    # not available, or Tasks package mismatch), fall back to a single-person
    # mediapipe.solutions.Pose instance so the user can still test detection.
    try:
        with mp_vision.PoseLandmarker.create_from_options(options) as landmarker:
            print("PoseLandmarker created, starting camera loop. Press ESC to quit.")
            frame_ts = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                combined = build_side_by_side_two_person(frame, person_w, person_h)

                # convert to RGB for mp.Image
                rgb = cv2.cvtColor(combined, cv2.COLOR_BGR2RGB)
                Image = getattr(mp_vision, 'Image', None)
                ImageFormat = getattr(mp_vision, 'ImageFormat', None)
                # Fallback to top-level mp.Image if tasks vision doesn't expose Image
                if Image is None or ImageFormat is None:
                    Image = getattr(mp, 'Image', None)
                    ImageFormat = getattr(mp, 'ImageFormat', None)
                if Image is None or ImageFormat is None:
                    print("[DEBUG] mp_vision.Image or mp.Image/ImageFormat unavailable; cannot use Tasks API for this frame")
                    break
                mp_image = Image(image_format=getattr(ImageFormat, 'SRGB', None), data=rgb)

                frame_ts = int(time.time() * 1000)
                res = landmarker.detect_for_video(mp_image, frame_ts)

                annotated = draw_landmarks_on_image(combined, res)

                cv2.imshow("MediaPipe Tasks Pose - side-by-side", annotated)
                key = cv2.waitKey(1) & 0xFF
                if key == 27:  # ESC
                    break
    except Exception as e:
        print(f"[DEBUG] Tasks PoseLandmarker unavailable or failed to init: {e}")
        print("Falling back to single-person mediapipe.solutions.Pose (not multi-person).")
        # Fallback: single-person Solutions API
        mp_pose = getattr(mp, 'solutions', None)
        if mp_pose is None or not hasattr(mp_pose, 'pose'):
            print("mediapipe.solutions.pose not available; cannot run fallback.")
        else:
            Pose = mp_pose.pose.Pose
            drawing_utils = getattr(mp_pose, 'drawing_utils', None)
            drawing_styles = getattr(mp_pose, 'drawing_styles', None)
            pose_conn = getattr(mp_pose, 'pose', None)
            pose_connections = getattr(pose_conn, 'POSE_CONNECTIONS', None) if pose_conn is not None else None
            with Pose(static_image_mode=False, model_complexity=1, smooth_landmarks=True, enable_segmentation=False, min_detection_confidence=0.5, min_tracking_confidence=0.5) as pose:
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break

                    combined = build_side_by_side_two_person(frame, person_w, person_h)
                    rgb = cv2.cvtColor(combined, cv2.COLOR_BGR2RGB)
                    results = pose.process(rgb)
                    annotated = combined.copy()
                    if results and getattr(results, 'pose_landmarks', None):
                        try:
                            if drawing_utils is not None and pose_connections is not None and drawing_styles is not None:
                                drawing_utils.draw_landmarks(annotated, results.pose_landmarks, pose_connections, drawing_styles.get_default_pose_landmarks_style())
                            elif drawing_utils is not None and pose_connections is not None:
                                drawing_utils.draw_landmarks(annotated, results.pose_landmarks, pose_connections)
                        except Exception:
                            # fall back to our simple drawing
                            annotated = draw_landmarks_on_image(combined, type('R', (), {'pose_landmarks':[results.pose_landmarks.landmark]}))

                    cv2.imshow("MediaPipe Solutions Pose (fallback) - side-by-side", annotated)
                    key = cv2.waitKey(1) & 0xFF
                    if key == 27:
                        break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Run MediaPipe Tasks PoseLandmarker on webcam with side-by-side duplicated crops to simulate two people.")
    p.add_argument("--model", help="Path to pose_landmarker task file (e.g. pose_landmarker_heavy.task)")
    p.add_argument("--camera", type=int, default=0, help="Camera index (default 0)")
    args = p.parse_args()
    main(model_path=args.model, camera_index=args.camera)
