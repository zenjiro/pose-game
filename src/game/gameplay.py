from __future__ import annotations

import random
import time
from typing import List

import numpy as np

from .entities import Rock


class RockManager:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.rocks: List[Rock] = []
        self._last_spawn = time.time()
        self.spawn_interval = 0.8  # seconds (tune)
        self.min_radius = 14
        self.max_radius = 36
        self.speed_min = 180.0
        self.speed_max = 360.0

    def maybe_spawn(self) -> None:
        now = time.time()
        if now - self._last_spawn < self.spawn_interval:
            return
        self._last_spawn = now

        r = random.randint(self.min_radius, self.max_radius)
        x = random.uniform(r, self.width - r)
        y = -r
        vx = random.uniform(-60.0, 60.0)
        vy = random.uniform(self.speed_min, self.speed_max)
        color = (80, 80, 80)
        self.rocks.append(Rock(x=x, y=y, vx=vx, vy=vy, r=r, color=color))

    def update(self, dt: float) -> None:
        for rock in self.rocks:
            rock.update(dt)
        # Remove off-screen
        self.rocks = [rk for rk in self.rocks if rk.y - rk.r < self.height + 5]

    def reset(self) -> None:
        self.rocks.clear()
