from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Tuple

import cv2
import numpy as np


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
        self.halo_scale: float = 1.8    # glow halo radius as fraction of particle radius
        self.glow_sigma: float = 6.0    # Gaussian blur sigma for glow layer
        self.core_weight: float = 1.0   # weight for core layer when compositing
        self.glow_weight: float = 0.85  # weight for glow layer when compositing

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
        for _ in range(count):
            ang = random.random() * math.tau
            spd = random.uniform(speed_min, speed_max)
            vx = math.cos(ang) * spd
            vy = math.sin(ang) * spd
            size = random.uniform(size_min, size_max)
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

    def draw(self, frame: np.ndarray) -> None:
        # Draw particles using a glow pass so overlapping particles blend naturally.
        # We accumulate into two float32 layers (core + glow), blur the glow,
        # then additively blend back into the frame.
        h, w = frame.shape[:2]
        if not self.use_glow:
            for p in self.particles:
                cx = int(p.x)
                cy = int(p.y)
                if cx < -5 or cy < -5 or cx >= w + 5 or cy >= h + 5:
                    continue
                col = p.color()
                rad = p.radius()
                cv2.circle(frame, (cx, cy), rad, col, -1, cv2.LINE_AA)
            return

        core_layer = np.zeros((h, w, 3), dtype=np.float32)
        glow_layer = np.zeros((h, w, 3), dtype=np.float32)

        for p in self.particles:
            cx = int(p.x)
            cy = int(p.y)
            if cx < -5 or cy < -5 or cx >= w + 5 or cy >= h + 5:
                continue
            base_col = p.color()
            # Fade intensity by life progress (smooth out at the end)
            age = p.t()  # 0 at birth -> 1 at death
            intensity = float(max(0.0, 1.0 - age))
            intensity = intensity * intensity  # ease-out
            colf = (base_col[0] * intensity, base_col[1] * intensity, base_col[2] * intensity)

            rad = p.radius()
            core_r = max(1, int(rad * self.core_scale))
            halo_r = max(core_r + 1, int(rad * self.halo_scale))

            cv2.circle(core_layer, (cx, cy), core_r, colf, -1, cv2.LINE_AA)
            cv2.circle(glow_layer, (cx, cy), halo_r, colf, -1, cv2.LINE_AA)

        if self.glow_sigma > 0:
            glow_layer = cv2.GaussianBlur(glow_layer, ksize=(0, 0), sigmaX=self.glow_sigma, sigmaY=self.glow_sigma)

        frame_f = frame.astype(np.float32)
        accum = frame_f
        if self.core_weight != 0:
            accum = cv2.add(accum, core_layer * float(self.core_weight))
        if self.glow_weight != 0:
            accum = cv2.add(accum, glow_layer * float(self.glow_weight))
        np.clip(accum, 0.0, 255.0, out=accum)
        frame[:, :, :] = accum.astype(np.uint8)
