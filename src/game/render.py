from __future__ import annotations

from typing import Dict, List
from .entities import Rock

import cv2
import numpy as np

from .pose import Circle


def draw_circles(frame: np.ndarray, groups: Dict[str, List[Circle]]) -> None:
    """Overlay head/hands/feet circles on the frame in-place."""
    colors = {
        "head": (0, 200, 255),   # orange-ish
        "hands": (60, 220, 60),  # green
        "feet": (255, 80, 80),   # blue-ish red
    }
    thickness = 2

    for key, circles in groups.items():
        color = colors.get(key, (255, 255, 255))
        for c in circles:
            cv2.circle(frame, (int(c.x), int(c.y)), int(c.r), color, thickness, cv2.LINE_AA)


def put_fps(frame: np.ndarray, fps: float) -> None:
    text = f"FPS: {fps:.1f}"
    cv2.putText(frame, text, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (240, 240, 240), 2, cv2.LINE_AA)


def draw_rocks(frame: np.ndarray, rocks: List[Rock]) -> None:
    for rk in rocks:
        cv2.circle(frame, (int(rk.x), int(rk.y)), int(rk.r), rk.color, -1, cv2.LINE_AA)
        # Simple shading
        cv2.circle(frame, (int(rk.x - rk.r * 0.3), int(rk.y - rk.r * 0.3)), int(rk.r * 0.3), (100, 100, 100), -1, cv2.LINE_AA)
