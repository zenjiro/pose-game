from __future__ import annotations

from typing import Dict, List
from .entities import Rock

import cv2
import numpy as np

from .pose import Circle
import arcade


def draw_circles(frame: np.ndarray, groups: Dict[str, List[Circle]], color_shift: int = 0, color: tuple[int, int, int] | None = None, prof=None) -> None:
    """OpenCV overlay for head/hands/feet circles (kept for compatibility)."""
    base_colors = {
        "head": (0, 200, 255),
        "hands": (60, 220, 60),
        "feet": (255, 80, 80),
    }
    thickness = 2
    for key, circles in groups.items():
        if color is not None:
            use_color = color
        else:
            base = base_colors.get(key, (255, 255, 255))
            use_color = tuple(int((c + color_shift) % 256) for c in base)
        for c in circles:
            cv2.circle(frame, (int(c.x), int(c.y)), int(c.r), use_color, thickness, cv2.LINE_AA)


def draw_circles_arcade(groups: Dict[str, List[Circle]], height: int, color_shift: int = 0, color: tuple[int, int, int] | None = None, thickness: float = 2.0, prof=None) -> None:
    """Arcade version: draw head/hands/feet circles as outlines.
    Flip Y because Arcade's origin is bottom-left but our coordinates are top-left.
    """
    base_colors = {
        "head": (0, 200, 255),
        "hands": (60, 220, 60),
        "feet": (255, 80, 80),
    }
    for key, circles in groups.items():
        if color is not None:
            use_color = color
        else:
            base = base_colors.get(key, (255, 255, 255))
            use_color = tuple(int((c + color_shift) % 256) for c in base)
        # BGR -> RGB for Arcade
        col = (use_color[2], use_color[1], use_color[0])
        for c in circles:
            x = float(c.x)
            y = float(height - c.y)
            r = float(c.r)
            arcade.draw_circle_outline(x, y, r, col, border_width=thickness)


def put_fps(frame: np.ndarray, fps: float) -> None:
    text = f"FPS: {fps:.1f}"
    cv2.putText(frame, text, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (240, 240, 240), 2, cv2.LINE_AA)


def draw_rocks(frame: np.ndarray, rocks: List[Rock]) -> None:
    for rk in rocks:
        cv2.circle(frame, (int(rk.x), int(rk.y)), int(rk.r), rk.color, -1, cv2.LINE_AA)
        cv2.circle(frame, (int(rk.x - rk.r * 0.3), int(rk.y - rk.r * 0.3)), int(rk.r * 0.3), (100, 100, 100), -1, cv2.LINE_AA)
        try:
            if getattr(rk, "hit", False):
                cv2.circle(frame, (int(rk.x), int(rk.y)), int(rk.r + 4), (0, 0, 200), 3, cv2.LINE_AA)
        except Exception:
            pass


def draw_rocks_arcade(rocks: List[Rock], height: int) -> None:
    for rk in rocks:
        x = float(rk.x)
        y = float(height - rk.y)
        r = float(rk.r)
        col = (rk.color[2], rk.color[1], rk.color[0])
        arcade.draw_circle_filled(x, y, r, col)
        arcade.draw_circle_filled(x - r * 0.3, y + r * 0.3, r * 0.3, (100, 100, 100))
        try:
            if getattr(rk, "hit", False):
                arcade.draw_circle_outline(x, y, r + 4, (200, 0, 0), border_width=3)
        except Exception:
            pass
