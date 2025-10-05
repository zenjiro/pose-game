from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Tuple
import time

import arcade

# Internal particle used for continuous hand glow
@dataclass
class HandParticle:
    # Relative offset from hand center, maintained implicitly by angle/dist
    angle: float
    dist: float
    speed: float
    life: float
    max_life: float
    size: float
    color_bgr: Tuple[int, int, int]

    def update(self, dt: float) -> None:
        if dt <= 0:
            return
        self.dist += self.speed * dt
        self.life -= dt

    def alive(self) -> bool:
        return self.life > 0.0


class HandGlowManager:
    """Maintains a soft, always-on hand glow for up to 2 players x 2 hands.

    - 64 particles per hand (max 256 total)
    - Particles drift outwards slowly and fade
    - Colors: P1 red, P2 blue (BGR)
    - No gravity; particles are re-emitted to maintain constant count
    - Render path: render particles into an offscreen texture, apply separable Gaussian blur,
      then composite additively over the scene.
    """

    def __init__(self, ctx, width: int, height: int, particles_per_hand: int = 64) -> None:
        self.ctx = ctx
        self.width = width
        self.height = height
        self.particles_per_hand = max(1, int(particles_per_hand))
        # hand_id -> particles
        self.hands: Dict[str, List[HandParticle]] = {}
        self.hand_centers: Dict[str, Tuple[float, float]] = {}
        self.hand_colors: Dict[str, Tuple[int, int, int]] = {}

        # GL resources
        # Two framebuffers for ping-pong blur
        self.fbo_ok = False
        try:
            self._init_gl_resources()
            self.fbo_ok = True
        except Exception as e:
            # Fallback: draw directly without FBO/blur
            print(f"[WARN] HandGlow: GL resources init failed, using fallback: {e}")
            self.fbo_ok = False

    def _init_gl_resources(self) -> None:
        # Color textures for FBOs
        self.tex_a = self.ctx.texture(size=(self.width, self.height), components=4)
        self.tex_b = self.ctx.texture(size=(self.width, self.height), components=4)
        self.fbo_a = self.ctx.framebuffer(color_attachments=[self.tex_a])
        self.fbo_b = self.ctx.framebuffer(color_attachments=[self.tex_b])
        # Fullscreen quad and shaders
        import array
        vs = """#version 330\nin vec2 in_vert; out vec2 v_uv; void main(){ v_uv=in_vert*0.5+0.5; gl_Position=vec4(in_vert,0.0,1.0);}"""
        fs_blur = """#version 330\nuniform sampler2D u_tex;\nuniform vec2 u_texel;\nuniform vec2 u_dir;\nuniform float u_sigma;\nin vec2 v_uv;\nout vec4 f_color;\nconst int R = 7;\nfloat gauss(float x, float s){ return exp(-0.5*x*x/(s*s)); }\nvoid main(){\n    vec4 sum = vec4(0.0);\n    float norm = 0.0;\n    for(int i=-R;i<=R;++i){\n        float w = gauss(float(i), u_sigma);\n        vec2 uv = v_uv + u_dir * u_texel * float(i);\n        sum += texture(u_tex, uv) * w;\n        norm += w;\n    }\n    f_color = sum / max(norm, 1e-6);\n}\n"""
        fs_passthrough = """#version 330\nuniform sampler2D u_tex;\nin vec2 v_uv;\nout vec4 f_color;\nvoid main(){\n    vec4 c = texture(u_tex, v_uv);\n    f_color = c;\n}\n"""
        self.blur_prog = self.ctx.program(vertex_shader=vs, fragment_shader=fs_blur)
        self.blit_prog = self.ctx.program(vertex_shader=vs, fragment_shader=fs_passthrough)
        # Prefer geometry helper if available
        try:
            from arcade.gl.geometry import quad_2d_fs
            self.quad = quad_2d_fs()
            self.vbo = None
            self.vao = None
        except Exception:
            quad = array.array('f', [-1,-1, 1,-1, -1,1, 1,-1, 1,1, -1,1])
            # Some arcade.gl versions require keyword-only arguments
            try:
                self.vbo = self.ctx.buffer(data=quad.tobytes())
            except Exception:
                # Some contexts expose context.buffer as Buffer
                self.vbo = self.ctx.buffer
            try:
                self.vao = self.ctx.simple_vertex_array(self.blur_prog, self.vbo, 'in_vert')
            except Exception:
                try:
                    from arcade.gl import BufferDescription
                    desc = BufferDescription(self.vbo, '2f', ['in_vert'])
                    self.vao = self.ctx.geometry([desc])
                except Exception:
                    self.vao = None
            self.quad = None
        # Validate draw geometry; if unavailable, fall back to non-FBO path
        if getattr(self, 'quad', None) is None and getattr(self, 'vao', None) is None:
            raise RuntimeError("No draw geometry available for HandGlow")

    def _spawn_particle(self, color_bgr: Tuple[int,int,int]) -> HandParticle:
        angle = random.random() * math.tau
        dist = random.uniform(0.0, 8.0)
        speed = random.uniform(28.0, 65.0)  # px/s outward
        life = random.uniform(0.8, 1.4)
        size = random.uniform(6.0, 12.0)
        return HandParticle(angle=angle, dist=dist, speed=speed, life=life, max_life=life, size=size, color_bgr=color_bgr)

    def _ensure_hand(self, hand_id: str, color_bgr: Tuple[int,int,int]) -> None:
        if hand_id not in self.hands:
            self.hands[hand_id] = []
        self.hand_colors[hand_id] = color_bgr
        # Maintain target count
        hp = self.hands[hand_id]
        while len(hp) < self.particles_per_hand:
            hp.append(self._spawn_particle(color_bgr))
        if len(hp) > self.particles_per_hand:
            del hp[self.particles_per_hand:]

    def update_hands(self, players_hands: List[List[Tuple[float, float]]], dt: float) -> None:
        """players_hands: list for each player -> list of (x,y) for up to two hands.
        Maintains particles per hand and updates simulation.
        """
        # Build current ids and centers
        current_ids = set()
        for pid, hands in enumerate(players_hands):
            # Sort hands by x to get stable left/right ordering
            hands_sorted = sorted(hands, key=lambda t: t[0])[:2]
            for hid, (hx, hy) in enumerate(hands_sorted):
                hand_id = f"p{pid}_h{hid}"
                color_bgr = (0,0,255) if pid == 0 else (255,0,0)  # P1 red, P2 blue (BGR)
                current_ids.add(hand_id)
                self._ensure_hand(hand_id, color_bgr)
                self.hand_centers[hand_id] = (float(hx), float(hy))
                # Update particles
                plist = self.hands[hand_id]
                for i, p in enumerate(plist):
                    p.update(dt)
                    if not p.alive():
                        # Respawn near center, keep list size constant
                        plist[i] = self._spawn_particle(color_bgr)
                # Top up in case list shrank (shouldn't happen, but be safe)
                while len(plist) < self.particles_per_hand:
                    plist.append(self._spawn_particle(color_bgr))
        # Remove hands that are no longer present
        stale = [hid for hid in list(self.hands.keys()) if hid not in current_ids]
        for hid in stale:
            del self.hands[hid]
            if hid in self.hand_centers:
                del self.hand_centers[hid]
            if hid in self.hand_colors:
                del self.hand_colors[hid]

    def _draw_particles_to_fbo(self, fbo) -> None:
        # Activate FBO and draw as filled circles with additive color (alpha via size-based intensity)
        with fbo.activate():
            try:
                fbo.clear(color=(0, 0, 0, 0))
            except Exception:
                # Some versions may accept positional floats
                try:
                    fbo.clear(0.0, 0.0, 0.0, 0.0)
                except Exception:
                    pass
            self._draw_particles_to_current_fb()

    def _draw_particles_to_current_fb(self) -> None:
        # Draw circles at current hand centers + particle offsets on the currently bound framebuffer
        for hand_id, plist in self.hands.items():
            cx, cy = self.hand_centers.get(hand_id, (0.0, 0.0))
            color_bgr = self.hand_colors.get(hand_id, (255,255,255))
            col_rgb = (int(color_bgr[2]), int(color_bgr[1]), int(color_bgr[0]))
            for p in plist:
                x = float(cx + math.cos(p.angle) * p.dist)
                y = float(cy + math.sin(p.angle) * p.dist)
                age = 1.0 - max(0.0, min(1.0, p.life / max(p.max_life, 1e-6)))
                # Fade out towards the end; keep a soft core
                alpha = int(220 * (1.0 - age) * (1.0 - 0.1 * age))
                r = max(1.0, p.size)
                arcade.draw_circle_filled(x, self.height - y, r, (*col_rgb, alpha))

    def _blur(self, src_tex, dst_fbo, dir_: Tuple[float, float], sigma: float = 4.0) -> None:
        dst_tex = dst_fbo.color_attachments[0]
        try:
            self.ctx.screen.use()  # ensure default framebuffer binding is known before switching
        except Exception:
            pass
        # Render to destination FBO
        with dst_fbo.activate():
            try:
                dst_fbo.clear(color=(0, 0, 0, 0))
            except Exception:
                try:
                    dst_fbo.clear(0.0, 0.0, 0.0, 0.0)
                except Exception:
                    pass
            # Bind program and uniforms
            self.blur_prog['u_tex'] = 0
            self.blur_prog['u_texel'] = (1.0 / src_tex.width, 1.0 / src_tex.height)
            self.blur_prog['u_dir'] = dir_
            self.blur_prog['u_sigma'] = sigma
            src_tex.use(0)
            try:
                if getattr(self, 'quad', None) is not None:
                    self.quad.render(program=self.blur_prog)
                elif getattr(self, 'vao', None) is not None:
                    self.vao.render()
                else:
                    vao = self.ctx.simple_vertex_array(self.blur_prog, self.vbo, 'in_vert')
                    vao.render()
            except Exception:
                pass

    def _draw_core_halos(self) -> None:
        # Draw a soft halo at each hand center to guarantee visibility
        for hand_id in self.hands.keys():
            cx, cy = self.hand_centers.get(hand_id, (0.0, 0.0))
            bgr = self.hand_colors.get(hand_id, (255,255,255))
            rgb = (int(bgr[2]), int(bgr[1]), int(bgr[0]))
            y = self.height - cy
            # Three-layer halo
            arcade.draw_circle_filled(cx, y, 36, (*rgb, 56))
            arcade.draw_circle_filled(cx, y, 22, (*rgb, 92))
            arcade.draw_circle_filled(cx, y, 12, (*rgb, 140))

    def draw(self) -> None:
        """Render hand glow over the default framebuffer."""
        # Store current GL state to restore after glow
        current_program = getattr(self.ctx, 'current_program', None)
        current_blend = None
        try:
            current_blend = self.ctx.is_enabled(self.ctx.BLEND)
        except Exception:
            pass

        if self.fbo_ok:
            # 1) Draw source particles to tex_a
            self._draw_particles_to_fbo(self.fbo_a)
            # 2) Blur horizontally into tex_b
            self._blur(self.tex_a, self.fbo_b, (1.0, 0.0), sigma=4.0)
            # 3) Blur vertically back into tex_a
            self._blur(self.tex_b, self.fbo_a, (0.0, 1.0), sigma=4.0)
            # 4) Composite tex_a to screen (alpha blending)
            try:
                self.ctx.screen.use()
            except Exception:
                pass
            # Enable blending for alpha compositing
            try:
                self.ctx.enable(self.ctx.BLEND)
                self.ctx.blend_func = (self.ctx.SRC_ALPHA, self.ctx.ONE_MINUS_SRC_ALPHA)
            except Exception:
                pass
            prog = self.blit_prog
            try:
                prog.use()
            except Exception:
                pass
            prog['u_tex'] = 0
            self.tex_a.use(0)
            try:
                if getattr(self, 'quad', None) is not None:
                    # geometry helper path
                    self.quad.render(program=prog)
                elif getattr(self, 'vao', None) is not None:
                    try:
                        self.vao.render()
                    except Exception:
                        pass
                else:
                    try:
                        vao = self.ctx.simple_vertex_array(prog, self.vbo, 'in_vert')
                        vao.render()
                    except Exception:
                        pass
            except Exception:
                pass
            # Also draw a core halo to ensure visibility on all hardware
            self._draw_core_halos()
        else:
            # Fallback: draw particles directly without blur to ensure visibility
            try:
                self.ctx.screen.use()
            except Exception:
                pass
            # Enable blending for alpha compositing
            try:
                self.ctx.enable(self.ctx.BLEND)
                self.ctx.blend_func = (self.ctx.SRC_ALPHA, self.ctx.ONE_MINUS_SRC_ALPHA)
            except Exception:
                pass
            self._draw_particles_to_current_fb()
            self._draw_core_halos()

        # Restore GL state
        try:
            if current_blend is False:
                self.ctx.disable(self.ctx.BLEND)
            elif current_blend is True:
                self.ctx.enable(self.ctx.BLEND)
        except Exception:
            pass
        try:
            if current_program is not None:
                current_program.use()
            else:
                # Unbind any program to restore default state
                try:
                    self.ctx.disable_program()
                except Exception:
                    pass
        except Exception:
            pass
