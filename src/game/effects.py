from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Tuple

import arcade


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    size: float
    color_start: Tuple[int, int, int]  # BGR
    color_end: Tuple[int, int, int]    # BGR
    gravity: float = 0.0

    def update(self, dt: float) -> None:
        # Simple physics: velocity + optional gravity
        self.vy += self.gravity * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.life -= dt

    def alive(self) -> bool:
        return self.life > 0.0

    def t(self) -> float:
        # 0 -> at birth, 1 -> at death
        return max(0.0, min(1.0, 1.0 - (self.life / self.max_life) if self.max_life > 1e-6 else 1.0))

    def color(self) -> Tuple[int, int, int]:
        # Linear interpolation BGR
        tt = self.t()
        b = int((1 - tt) * self.color_start[0] + tt * self.color_end[0])
        g = int((1 - tt) * self.color_start[1] + tt * self.color_end[1])
        r = int((1 - tt) * self.color_start[2] + tt * self.color_end[2])
        return (b, g, r)

    def radius(self) -> int:
        # Shrink over time
        tt = self.t()
        return max(1, int(self.size * (1.0 - 0.6 * tt)))


class EffectsManager:
    def __init__(self) -> None:
        self.particles: List[Particle] = []
        # Glow/blend tuning (simulates Arcade's glow blending via blur + additive)
        self.use_glow: bool = True
        self.core_scale: float = 0.55   # crisp core radius as fraction of particle radius
        self.halo_scale: float = 1.08   # glow halo radius as fraction of particle radius (reduced to 60%)
        self.glow_sigma: float = 3.6    # Gaussian blur sigma for glow layer (reduced to 60%)
        self.core_weight: float = 1.0   # weight for core layer when compositing
        self.glow_weight: float = 0.85  # weight for glow layer when compositing
        # Performance/quality knobs
        self.fps_threshold_for_glow: float = 10.0  # enable glow only when FPS >= threshold
        self.count_scale: float = 0.5   # spawn half as many particles
        self.size_scale: float = 1.5    # particles 1.5x size

    def spawn_explosion(self, x: float, y: float,
                         base_color: Tuple[int, int, int] = (0, 220, 255),
                         count: int = 56,
                         speed_min: float = 90.0, speed_max: float = 240.0,
                         life_min: float = 1.0, life_max: float = 2.2,
                         gravity_min: float = -90.0, gravity_max: float = -30.0,
                         end_color: Tuple[int, int, int] | None = None,
                         size_min: float = 2.0, size_max: float = 6.0) -> None:
        # base_color is BGR. Keep brighter overall, fade but not to full black
        _end_color = end_color if end_color is not None else (40, 60, 60)
        scaled_count = max(1, int(count * getattr(self, 'count_scale', 1.0)))
        for _ in range(scaled_count):
            ang = random.random() * math.tau
            spd = random.uniform(speed_min, speed_max)
            vx = math.cos(ang) * spd
            vy = math.sin(ang) * spd
            size = random.uniform(size_min, size_max) * getattr(self, 'size_scale', 1.0)
            life = random.uniform(life_min, life_max)
            # Gravity: allow overrides; positive = downward, negative = upward (screen y grows down)
            gravity = random.uniform(gravity_min, gravity_max)
            # Small color variance
            jitter = lambda c: max(0, min(255, int(c + random.uniform(-20, 20))))
            start_color = (jitter(base_color[0]), jitter(base_color[1]), jitter(base_color[2]))
            self.particles.append(Particle(
                x=x, y=y, vx=vx, vy=vy, life=life, max_life=life, size=size,
                color_start=start_color, color_end=_end_color, gravity=gravity
            ))

    def update(self, dt: float) -> None:
        # Update and cull
        if dt <= 0:
            return
        for p in self.particles:
            p.update(dt)
        self.particles = [p for p in self.particles if p.alive()]

    def draw(self, height: int, fps: float | None = None) -> None:
        """Draw particles using Arcade. Uses a simple core + halo approach with alpha blending for speed.
        Glow is enabled only if FPS is above threshold (if provided).
        """
        effective_glow = self.use_glow and (fps is None or fps >= getattr(self, 'fps_threshold_for_glow', 0.0))
        for p in self.particles:
            cx = float(p.x)
            cy = float(height - p.y)
            base_col = p.color()
            age = p.t()
            intensity = float(max(0.0, 1.0 - age))
            intensity = intensity * intensity
            # Convert to Arcade RGB with alpha based on intensity
            col_rgb = (int(base_col[2]), int(base_col[1]), int(base_col[0]))
            rad = float(p.radius()) * getattr(self, 'size_scale', 1.0)
            if effective_glow:
                halo_r = max(1.0, rad * self.halo_scale)
                # Low alpha halo
                arcade.draw_circle_filled(cx, cy, halo_r, (*col_rgb, int(60 * intensity + 20)))
            # Core: higher alpha
            core_r = max(1.0, rad * self.core_scale)
            arcade.draw_circle_filled(cx, cy, core_r, (*col_rgb, int(180 * intensity + 40)))