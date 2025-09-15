from __future__ import annotations

from typing import Dict, List
from .entities import Rock

import cv2
import numpy as np

from .pose import Circle


def draw_circles(frame: np.ndarray, groups: Dict[str, List[Circle]], color_shift: int = 0) -> None:
    """Overlay head/hands/feet circles on the frame in-place.
    color_shift can be used to differentiate players (e.g., +128 for player 2 hues).
    """
    base_colors = {
        "head": (0, 200, 255),   # orange-ish
        "hands": (60, 220, 60),  # green
        "feet": (255, 80, 80),   # blue-ish red
    }
    thickness = 2

    # Debug: print incoming groups once per run to verify drawing inputs
    if not hasattr(draw_circles, "_debug_printed"):
        draw_circles._debug_printed = False
    if not draw_circles._debug_printed:
        try:
            print(f"[draw_circles] groups={{k: len(v) for k,v in groups.items()}} color_shift={color_shift}")
            for k, v in groups.items():
                if v:
                    print(f"[draw_circles] first {k} = ({v[0].x},{v[0].y},{v[0].r})")
        except Exception:
            pass
        draw_circles._debug_printed = True

    for key, circles in groups.items():
        base = base_colors.get(key, (255, 255, 255))
        color = tuple(int((c + color_shift) % 256) for c in base)
        for c in circles:
            # Outline-only drawing (restore original behavior)
            cv2.circle(frame, (int(c.x), int(c.y)), int(c.r), color, thickness, cv2.LINE_AA)


def put_fps(frame: np.ndarray, fps: float) -> None:
    text = f"FPS: {fps:.1f}"
    cv2.putText(frame, text, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (240, 240, 240), 2, cv2.LINE_AA)


def draw_rocks(frame: np.ndarray, rocks: List[Rock]) -> None:
    for rk in rocks:
        cv2.circle(frame, (int(rk.x), int(rk.y)), int(rk.r), rk.color, -1, cv2.LINE_AA)
        # Simple shading
        cv2.circle(frame, (int(rk.x - rk.r * 0.3), int(rk.y - rk.r * 0.3)), int(rk.r * 0.3), (100, 100, 100), -1, cv2.LINE_AA)
        # If rock was hit, draw a red outline to indicate the collision
        try:
            if getattr(rk, "hit", False):
                cv2.circle(frame, (int(rk.x), int(rk.y)), int(rk.r + 4), (0, 0, 200), 3, cv2.LINE_AA)
        except Exception:
            pass
