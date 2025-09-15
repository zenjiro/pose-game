from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import mediapipe as mp


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
    ) -> None:
        self._mp_pose = mp.solutions.pose
        self._pose = self._mp_pose.Pose(
            static_image_mode=False,
            model_complexity=model_complexity,
            smooth_landmarks=smooth_landmarks,
            enable_segmentation=False,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    def close(self) -> None:
        try:
            self._pose.close()
        except Exception:
            pass

    def __del__(self) -> None:
        self.close()

    def process(self, frame_bgr: np.ndarray) -> Dict[str, List[Circle]]:
        """
        Process a BGR frame and return circles for head, hands, and feet for a single person.
        """
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        results = self._pose.process(rgb)

        if not results.pose_landmarks:
            return {"head": [], "hands": [], "feet": []}

        lm = results.pose_landmarks.landmark

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
