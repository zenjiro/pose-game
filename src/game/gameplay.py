from __future__ import annotations

import random
import time
from typing import List, Tuple

from .entities import Rock
from .collision import circles_overlap
import time


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
        now = time.time()
        for rock in self.rocks:
            rock.update(dt)
            # If rock was hit some time ago, remove it after short effect
            if rock.hit and rock.hit_time is not None and now - rock.hit_time > 0.25:
                rock.y = self.height + rock.r + 1000  # push offscreen; cleanup below

        # Remove off-screen
        self.rocks = [rk for rk in self.rocks if rk.y - rk.r < self.height + 5]

    def handle_head_collisions(self, head_circles: List[Tuple[int, int, int]]) -> int:
        """Check head circles (list of (x,y,r)). Return number of hits detected.
        Marks rocks as hit and returns number of rocks that hit a head this frame.
        """
        hits = 0
        now = time.time()
        for rk in self.rocks:
            if rk.hit:
                continue
            for hx, hy, hr in head_circles:
                if circles_overlap((rk.x, rk.y, rk.r), (hx, hy, hr)):
                    rk.hit = True
                    rk.hit_time = now
                    hits += 1
                    break
        return hits

    def reset(self) -> None:
        self.rocks.clear()
