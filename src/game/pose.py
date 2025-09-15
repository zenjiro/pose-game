from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import mediapipe as mp

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
    ) -> None:
        self.max_people = max(1, int(max_people))
        self._single = None
        self._multi = None
        # Prefer Tasks API when available and max_people > 1. If Tasks initialization
        # fails for any reason, fall back to the single-person Solutions API so
        # `process()` continues to return detections.
        if TASKS_AVAILABLE and self.max_people > 1:
            # Build BaseOptions (use built-in model by leaving model_asset_path=None)
            base_options = mp_python.BaseOptions(model_asset_path=None)
            # Try to construct PoseLandmarkerOptions with tracking option first.
            try:
                options = mp_vision.PoseLandmarkerOptions(
                    base_options=base_options,
                    running_mode=mp_vision.RunningMode.VIDEO,
                    num_poses=self.max_people,
                    min_pose_detection_confidence=min_detection_confidence,
                    min_pose_tracking_confidence=min_tracking_confidence,
                )
                self._multi = mp_vision.PoseLandmarker.create_from_options(options)
            except TypeError:
                # Some versions of the Tasks API don't accept min_pose_tracking_confidence.
                # Retry without the tracking option.
                try:
                    options = mp_vision.PoseLandmarkerOptions(
                        base_options=base_options,
                        running_mode=mp_vision.RunningMode.VIDEO,
                        num_poses=self.max_people,
                        min_pose_detection_confidence=min_detection_confidence,
                    )
                    self._multi = mp_vision.PoseLandmarker.create_from_options(options)
                except Exception:
                    # Failure creating the Tasks API object; leave self._multi as None
                    # and fall through to initialize the single-person API.
                    self._multi = None

        # If Tasks API wasn't used or failed to initialize, initialize the
        # single-person Solutions API so `process()` can still detect landmarks.
        if self._multi is None:
            self._mp_pose = mp.solutions.pose
            self._single = self._mp_pose.Pose(
                static_image_mode=False,
                model_complexity=model_complexity,
                smooth_landmarks=smooth_landmarks,
                enable_segmentation=False,
                min_detection_confidence=min_detection_confidence,
                min_tracking_confidence=min_tracking_confidence,
            )
            self._backend = "solutions_single"
        else:
            self._backend = "tasks_multi"

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

        if self._multi is not None:
            mp_image = mp_vision.Image(image_format=mp_vision.ImageFormat.SRGB, data=rgb)
            # Use a dummy timestamp; we don't rely on temporal filtering here
            res = self._multi.detect_for_video(mp_image, 0)
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
            return []
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
