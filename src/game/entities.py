from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass
class Rock:
    x: float
    y: float
    vx: float
    vy: float
    r: int
    color: Tuple[int, int, int]  # BGR

    def update(self, dt: float) -> None:
        self.x += self.vx * dt
        self.y += self.vy * dt
