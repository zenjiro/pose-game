from __future__ import annotations

from typing import Tuple

def circles_overlap(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> bool:
    """Return True if two circles (x,y,r) overlap."""
    ax, ay, ar = a
    bx, by, br = b
    dx = ax - bx
    dy = ay - by
    return (dx * dx + dy * dy) < ((ar + br) * (ar + br))
