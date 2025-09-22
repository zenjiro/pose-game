from __future__ import annotations

import random
import time
from typing import List, Tuple

from .entities import Rock
from .collision import circles_overlap


class RockManager:
    def __init__(self, width: int, height: int, audio_manager=None) -> None:
        self.width = width
        self.height = height
        self.rocks: List[Rock] = []
        self._last_spawn = time.time()
        self.spawn_interval = 0.8  # seconds (tune)
        self.min_radius = 14
        self.max_radius = 36
        self.speed_min = 180.0
        self.speed_max = 360.0
        self.audio_manager = audio_manager

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
        
        # Play rock drop sound
        if self.audio_manager:
            self.audio_manager.play_rock_drop()

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
        # Keep for backward compatibility; delegate to generic handler
        events = self.handle_collisions(kind="head", circles=head_circles)
        return events.get("hits", 0)

    def handle_collisions(self, kind: str, circles: List[Tuple[int, int, int]]) -> dict:
        """Generic collision handler.

        kind: "head" | "hands" | "feet" | ...
        circles: list of (x,y,r) tuples representing target circles to check.

        Returns a dict with summary:
          {"hits": int, "positions": List[(x,y)]}
        Marks rocks as hit when collision is detected. Behavior can be specialized per kind.
        """
        hits = 0
        positions: List[Tuple[float, float]] = []
        now = time.time()
        for rk in self.rocks:
            if rk.hit:
                continue
            for cx, cy, cr in circles:
                if circles_overlap((rk.x, rk.y, rk.r), (cx, cy, cr)):
                    # For head/hands/feet collisions we mark the rock as hit (destroy/disable),
                    # external systems (score/lives/effects) can react based on kind.
                    rk.hit = True
                    rk.hit_time = now
                    hits += 1
                    positions.append((rk.x, rk.y))
                    break

        return {"hits": hits, "positions": positions, "kind": kind}

    def reset(self) -> None:
        self.rocks.clear()
