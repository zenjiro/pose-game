from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import mediapipe as mp
# Import the pose solutions module explicitly so static analyzers (Pylance)
# recognize `pose` as an attribute. If import fails at runtime, we'll fall
# back to accessing `mp.solutions.pose`.
try:
    from mediapipe.solutions import pose as mp_pose_module  # type: ignore
except Exception:
    mp_pose_module = None

# Tasks API imports for multi-person
try:
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
    TASKS_AVAILABLE = True
except Exception:
    TASKS_AVAILABLE = False


@dataclass
class Circle:
    x: int
    y: int
    r: int


class PoseEstimator:
    def __init__(
        self,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
        model_complexity: int = 1,
        smooth_landmarks: bool = True,
        max_people: int = 2,
        tasks_model: Optional[str] = None,
        tasks_mode: Optional[str] = "video",
    ) -> None:
        self.max_people = max(1, int(max_people))
        # tasks_model: path to a MediaPipe Tasks pose landmarker model file (tflite/task file).
        # If None, we won't attempt to initialize the Tasks API even if available.
        self._tasks_model = tasks_model
        self._tasks_mode = (tasks_mode or "video").lower()
        print(f"[DEBUG] PoseEstimator.__init__: requested max_people={max_people} normalized={self.max_people} TASKS_AVAILABLE={TASKS_AVAILABLE} tasks_model={'provided' if tasks_model else 'none'}")
        self._single = None
        self._multi = None
        # Prefer Tasks API when available and max_people > 1. If Tasks initialization
        # fails for any reason, fall back to the single-person Solutions API so
        # `process()` continues to return detections.
        # Only try Tasks API when Tasks package is available, multi-person requested,
        # and a model path was explicitly provided.
        if TASKS_AVAILABLE and self.max_people > 1 and self._tasks_model:
            print("[DEBUG] PoseEstimator: attempting to initialize Tasks API for multi-person detection")
            # BaseOptions（delegate 指定なし）
            base_options = mp_python.BaseOptions(model_asset_path=self._tasks_model)
            # Try to construct PoseLandmarkerOptions with tracking option first.
            try:
                mode_map = {
                    "image": getattr(mp_vision.RunningMode, "IMAGE", None),
                    "video": getattr(mp_vision.RunningMode, "VIDEO", None),
                    "live": getattr(mp_vision.RunningMode, "LIVE_STREAM", None),
                }
                run_mode = mode_map.get(self._tasks_mode, getattr(mp_vision.RunningMode, "VIDEO", None))
                kwargs = dict(
                    base_options=base_options,
                    running_mode=run_mode,
                    num_poses=self.max_people,
                    min_pose_detection_confidence=min_detection_confidence,
                )
                # tracking conf may not be supported in some versions
                try:
                    kwargs["min_pose_tracking_confidence"] = min_tracking_confidence
                except Exception:
                    pass
                # LIVE_STREAM requires a callback
                if run_mode == getattr(mp_vision.RunningMode, "LIVE_STREAM", None):
                    # define callback
                    def _cb(result, output_image, timestamp_ms):
                        try:
                            h_oi = None; w_oi = None
                            try:
                                h_oi = getattr(output_image, "height", None)
                                w_oi = getattr(output_image, "width", None)
                            except Exception:
                                pass
                            if (h_oi is None) or (w_oi is None):
                                try:
                                    arr = output_image.numpy_view()
                                    h_oi, w_oi = arr.shape[:2]
                                except Exception:
                                    h_oi = w_oi = None
                            people_live = []
                            if getattr(result, "pose_landmarks", None):
                                for lms in result.pose_landmarks:
                                    if h_oi is not None and w_oi is not None:
                                        people_live.append(self._extract_person(lms, w_oi, h_oi))
                            self._last_people = people_live
                        except Exception:
                            pass
                    kwargs["result_callback"] = _cb
                options = mp_vision.PoseLandmarkerOptions(**kwargs)
                self._multi = mp_vision.PoseLandmarker.create_from_options(options)
            except Exception:
                # Failure creating the Tasks API object; leave self._multi as None
                # and fall through to initialize the single-person API.
                import traceback as _tb
                self._multi = None
                print("[DEBUG] PoseEstimator: Tasks API initialization failed, will fall back to Solutions API")
                try:
                    _tb.print_exc()
                except Exception:
                    print("[DEBUG] Could not print traceback for Tasks API init failure")

        elif TASKS_AVAILABLE and self.max_people > 1 and not self._tasks_model:
            # Tasks API is available but no model was provided.
            print("[DEBUG] PoseEstimator: MediaPipe Tasks available but no tasks_model provided; skipping Tasks API and using Solutions API (single-person)")

        # If Tasks API wasn't used or failed to initialize, initialize the
        # single-person Solutions API so `process()` can still detect landmarks.
        if self._multi is None:
            # Prefer explicit import if it succeeded, otherwise fall back to
            # `mp.solutions.pose` at runtime.
            mp_pose_mod = mp_pose_module if mp_pose_module is not None else getattr(mp, "solutions").pose
            self._mp_pose = mp_pose_mod
            self._single = self._mp_pose.Pose(
                static_image_mode=False,
                model_complexity=model_complexity,
                smooth_landmarks=smooth_landmarks,
                enable_segmentation=False,
                min_detection_confidence=min_detection_confidence,
                min_tracking_confidence=min_tracking_confidence,
            )
            self._backend = "solutions_single"
            print(f"[DEBUG] PoseEstimator: initialized backend={self._backend}")
        else:
            self._backend = "tasks_multi"
            print(f"[DEBUG] PoseEstimator: initialized backend={self._backend} (num_poses={self.max_people})")

    # initialization

    def close(self) -> None:
        try:
            if self._single is not None:
                self._single.close()
        except Exception:
            pass
        try:
            if self._multi is not None:
                self._multi.close()
        except Exception:
            pass

    def __del__(self) -> None:
        self.close()

    def process(self, frame_bgr: np.ndarray) -> List[Dict[str, List[Circle]]]:
        """
        Process a BGR frame and return, for each detected person, circles for head/hands/feet.
        Returns a list of dicts: [{"head": [...], "hands": [...], "feet": [...]}]
        """
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        people: List[Dict[str, List[Circle]]] = []
        # Debug: only print detailed circle contents for the first processed frame
        if not hasattr(self, "_debug_printed"):
            self._debug_printed = False

        # Use logger to report backend at debug level
        # determine backend for internal use

        # Throttle debug logging to every 3 seconds
        current_time = time.time()
        should_log = not hasattr(self, '_last_debug_time') or (current_time - getattr(self, '_last_debug_time', 0)) >= 3.0
        
        if should_log:
            self._last_debug_time = current_time
            print(f"[DEBUG] PoseEstimator.process: backend={getattr(self, '_backend', None)} frame={w}x{h}")
        
        if self._multi is not None:
            # Guard attribute access to satisfy static analyzers that may not
            # see `Image` and `ImageFormat` on the tasks vision module.
            Image = getattr(mp_vision, "Image", None)
            ImageFormat = getattr(mp_vision, "ImageFormat", None)
            # Fallback to top-level mp.Image if tasks vision doesn't expose Image
            if Image is None or ImageFormat is None:
                Image = getattr(mp, "Image", None)
                ImageFormat = getattr(mp, "ImageFormat", None)

            if Image is None or ImageFormat is None:
                if should_log:
                    print("[DEBUG] PoseEstimator: mp.Image or mp_vision.Image/ImageFormat unavailable; cannot use Tasks API for this frame")
                return []

            img_fmt = getattr(ImageFormat, "SRGB", None)
            mp_image = Image(image_format=img_fmt, data=rgb)
            # VIDEO mode requires a timestamp in milliseconds
            res = self._multi.detect_for_video(mp_image, int(time.time() * 1000))
            num = len(res.pose_landmarks) if res.pose_landmarks else 0
            if should_log:
                print(f"[DEBUG] Tasks API returned {num} pose sets")
            if not res.pose_landmarks:
                return []
            # res.pose_landmarks is list[list[NormalizedLandmark]] per person
            for lms in res.pose_landmarks:
                people.append(self._extract_person(lms, w, h))
            for i, p in enumerate(people):
                if not self._debug_printed:
                    self._debug_printed = True
            return people

        # Fallback to single-person solutions API
        results = self._single.process(rgb) if self._single is not None else None
        if not results or not results.pose_landmarks:
            if should_log:
                print("[DEBUG] Solutions API returned no pose_landmarks")
            return []
        lm_count = len(results.pose_landmarks.landmark) if results.pose_landmarks and results.pose_landmarks.landmark else 0
        if should_log:
            print(f"[DEBUG] Solutions API returned landmarks count={lm_count}")
        person = self._extract_person(results.pose_landmarks.landmark, w, h)
        people.append(person)
        if not getattr(self, "_debug_printed", False):
            self._debug_printed = True
        return people

    def _extract_person(self, lm, w: int, h: int) -> Dict[str, List[Circle]]:
        # lm: iterable of landmarks with x,y,visibility

        def get_xy(idx: int, vis_th: float = 0.5) -> Optional[Tuple[int, int, float]]:
            p = lm[idx]
            if p.visibility is not None and p.visibility < vis_th:
                return None
            if p.x is None or p.y is None:
                return None
            x = int(np.clip(p.x * w, 0, w - 1))
            y = int(np.clip(p.y * h, 0, h - 1))
            return x, y, float(p.visibility if p.visibility is not None else 1.0)

        # Key indices (MediaPipe Pose v0.10+ numbering)
        NOSE = 0
        LEFT_EAR = 7
        RIGHT_EAR = 8
        LEFT_WRIST = 15
        RIGHT_WRIST = 16
        LEFT_ANKLE = 27
        RIGHT_ANKLE = 28
        LEFT_FOOT_INDEX = 31
        RIGHT_FOOT_INDEX = 32

        nose = get_xy(NOSE, 0.4)
        le = get_xy(LEFT_EAR, 0.3)
        re = get_xy(RIGHT_EAR, 0.3)

        # Head circle estimation
        head: List[Circle] = []
        if le and re:
            cx = (le[0] + re[0]) // 2
            cy = (le[1] + re[1]) // 2
            ear_dist = int(np.hypot(le[0] - re[0], le[1] - re[1]))
            r = max(8, int(ear_dist * 0.6))
            head.append(Circle(cx, cy, r))
        elif nose:
            r = max(12, int(h * 0.06))
            head.append(Circle(nose[0], nose[1], r))

        # Hands
        hands: List[Circle] = []
        lw = get_xy(LEFT_WRIST, 0.4)
        rw = get_xy(RIGHT_WRIST, 0.4)
        hand_r = max(6, int(h * 0.025))
        if lw:
            hands.append(Circle(lw[0], lw[1], hand_r))
        if rw:
            hands.append(Circle(rw[0], rw[1], hand_r))

        # Feet (prefer foot_index; fallback to ankle)
        feet: List[Circle] = []
        lfi = get_xy(LEFT_FOOT_INDEX, 0.4)
        rfi = get_xy(RIGHT_FOOT_INDEX, 0.4)
        la = get_xy(LEFT_ANKLE, 0.4)
        ra = get_xy(RIGHT_ANKLE, 0.4)
        foot_r = max(8, int(h * 0.03))
        if lfi:
            feet.append(Circle(lfi[0], lfi[1], foot_r))
        elif la:
            feet.append(Circle(la[0], la[1], foot_r))
        if rfi:
            feet.append(Circle(rfi[0], rfi[1], foot_r))
        elif ra:
            feet.append(Circle(ra[0], ra[1], foot_r))

        return {"head": head, "hands": hands, "feet": feet}
