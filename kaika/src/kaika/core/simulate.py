"""E2 — Fluid simulation.  score + recipe -> fluid frames + velocity fields.

A Jos-Stam style stable-fluids solver (incompressible Navier-Stokes) in pure
NumPy with toroidal boundaries: exact FFT pressure projection, MacCormack
advection, fully deterministic (seed -> identical video), runs with no GPU.

The simulation is the *movement skeleton* and is alive at all times, not just on
onsets: a continuous curl-noise field stirs the fluid (scaled by loudness),
persistent dye emitters keep colour flowing, and audio events are accents on top
-- kicks inject anchored splats, hats pop everywhere, RMS drives vorticity, and
an upcoming drop is anticipated by sub-visible vortices (lookahead). Frames are
rendered HDR -> filmic tone-map + bloom over a dark field from a recipe palette.

Outputs, per run dir:
  fluid/%06d.png        RGB density frame (render_resolution)
  velocity/%06d.npy     (H, W, 2) float32 velocity field (sim resolution)
  fluid_stats.json      per-frame kinetic energy + density (for E5 sync check)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, List, Optional

import numpy as np
import cv2

from .score import Score
from .recipe import Recipe, FluidConfig

ProgressFn = Callable[[int, int], None]

# Maps recipe splat "force" to a sane velocity in cells/frame (avoids CFL blowup).
FORCE_K = 0.04
# Scales recipe vorticity into the velocity regime; confinement is a positive
# feedback, so this must keep the per-step force a small fraction of velocity.
VORT_K = 0.015
# Forcing / emission tuning (named so they are easy to find and adjust).
AMBIENT_FLOOR = 0.12        # ambient stir at silence, as a fraction of strength
KICK_JITTER = 0.09          # spread of kick spawn positions around the anchor
KICK_ANGLE_JITTER = 0.5     # radians of randomness on a kick's outward heading
WANDER_AMP = 0.16           # how far the kick anchor (centre of gravity) wanders
SOURCE_DECAY = 1.3          # emission envelope exponent (impulsive: peak at birth)
SOURCE_EXPAND = 0.8         # how much a source's radius grows over its life
JET_FRACTION = 0.35         # ongoing directional jet strength vs the initial impulse
BLOOM_THRESHOLD = 0.45      # luminance above which bloom is added


def _hex_to_rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)], np.float32)


def _tonemap(hdr: np.ndarray, exposure: float) -> np.ndarray:
    """HDR density -> filmic LDR: exponential exposure + mild gamma."""
    mapped = 1.0 - np.exp(-exposure * np.clip(hdr, 0.0, None))
    return np.clip(mapped, 0.0, 1.0) ** (1.0 / 1.15)


def _curl_noise(gx: np.ndarray, gy: np.ndarray, t: float, scale: float):
    """Divergence-free ambient velocity from the curl of a moving potential."""
    sx = gx * 2 * np.pi * scale
    sy = gy * 2 * np.pi * scale
    psi = (np.sin(sx + t) * np.cos(sy * 1.3 - 0.7 * t)
           + 0.6 * np.sin(sx * 0.7 - 1.1 * t) * np.sin(sy * 1.7 + 0.5 * t)
           + 0.4 * np.sin(sx * 1.9 + 0.3 * t) * np.cos(sy * 0.9 - 0.6 * t))
    u = (np.roll(psi, -1, 0) - np.roll(psi, 1, 0)) * 0.5     # dpsi/dy
    v = -(np.roll(psi, -1, 1) - np.roll(psi, 1, 1)) * 0.5    # -dpsi/dx
    peak = float(np.sqrt(u * u + v * v).max()) + 1e-6        # normalise to unit speed
    return (u / peak).astype(np.float32), (v / peak).astype(np.float32)


def _advance_sources(sim: "FluidSim", sources: List["_Source"], n: int) -> List["_Source"]:
    """Emit + propel every living source one step; return the survivors.

    Each source streams matter ALONG its heading (dye + a directional jet, not an
    isotropic blob), then self-propels and is carried by the flow, then ages out.
    """
    still: List[_Source] = []
    for s in sources:
        frac = s.age / s.life
        env = (1.0 - frac) ** SOURCE_DECAY        # impulsive: peak at birth -> 0
        r_now = s.radius * (1.0 + SOURCE_EXPAND * frac)
        sim.add_dye(s.x, s.y, r_now, s.color, s.emit * env)
        sim.add_force_at(s.x, s.y, r_now, s.dx * s.jet * env, s.dy * s.jet * env)
        xi = int(np.clip(s.x * n, 0, n - 1))
        yi = int(np.clip(s.y * n, 0, n - 1))
        s.x = (s.x + (s.speed * s.dx + s.drift * float(sim.u[yi, xi])) / n) % 1.0
        s.y = (s.y + (s.speed * s.dy + s.drift * float(sim.v[yi, xi])) / n) % 1.0
        s.age += 1
        if s.age < s.life:
            still.append(s)
    return still


def _render_frame(density: np.ndarray, exposure: float, bloom: float,
                  bloom_sigma: float, background: float) -> np.ndarray:
    """HDR density -> filmic tone-map + bloom over a dark field -> uint8 RGB."""
    ldr = _tonemap(density, exposure)
    if bloom > 0:
        bright = np.clip(ldr - BLOOM_THRESHOLD, 0.0, 1.0)
        ldr = ldr + bloom * cv2.GaussianBlur(bright, (0, 0), sigmaX=bloom_sigma)
    out = background + (1.0 - background) * np.clip(ldr, 0.0, 1.0)
    return (np.clip(out, 0.0, 1.0) * 255).astype(np.uint8)


@dataclass
class _Source:
    """A transient, directional dye source: born on a musical event, it streams
    matter along its heading (jet + self-propulsion), then fades and dies."""
    x: float
    y: float
    color: np.ndarray
    radius: float
    emit: float
    life: int
    drift: float
    dx: float
    dy: float
    speed: float
    jet: float
    age: int = 0


@dataclass
class SimResult:
    fluid_dir: Path
    velocity_dir: Path
    stats_path: Path
    n_frames: int
    resolution: int


class FluidSim:
    """Toroidal stable-fluids solver on an NxN grid."""

    def __init__(self, n: int, dissipation: float, viscosity: float, seed: int,
                 vel_dissipation: float = 0.96):
        self.n = n
        self.dissipation = dissipation
        self.vel_dissipation = vel_dissipation
        self.viscosity = viscosity
        self.rng = np.random.default_rng(seed)
        self.u = np.zeros((n, n), np.float32)
        self.v = np.zeros((n, n), np.float32)
        self.density = np.zeros((n, n, 3), np.float32)
        ys, xs = np.mgrid[0:n, 0:n]
        self.xs = xs.astype(np.float32)
        self.ys = ys.astype(np.float32)
        # Eigenvalues of the 5-point Poisson operator for the exact FFT solve.
        i = np.arange(n)
        a = (4.0 - 2 * np.cos(2 * np.pi * i / n)[:, None]
             - 2 * np.cos(2 * np.pi * i / n)[None, :])
        a[0, 0] = 1.0                       # guard DC; mean pressure is gauge-free
        self._poisson = a
        self._k3 = np.ones((3, 3), np.uint8)

    # ---- operators ---------------------------------------------------------
    def _advect(self, field: np.ndarray, u: np.ndarray, v: np.ndarray,
                dt: float) -> np.ndarray:
        """MacCormack advection (bilinear semi-Lagrangian + error correction).

        Two bilinear backtraces with a corrector pass remove most numerical
        diffusion, keeping crisp filaments; bilinear is max-principle stable
        (no cubic overshoot) and a min/max limiter clamps the corrector.
        Handles 1- or multi-channel fields in a single ``cv2.remap`` call.
        """
        mx = (self.xs - dt * u).astype(np.float32)
        my = (self.ys - dt * v).astype(np.float32)
        fwd = cv2.remap(field, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
        bx = (self.xs + dt * u).astype(np.float32)
        by = (self.ys + dt * v).astype(np.float32)
        back = cv2.remap(fwd, bx, by, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
        corrected = fwd + 0.5 * (field - back)
        hi = cv2.dilate(fwd, self._k3)
        lo = cv2.erode(fwd, self._k3)
        return np.clip(corrected, lo, hi).astype(np.float32)

    def _project(self, iters: int = 0) -> None:
        """Exact incompressibility via a spectral Poisson solve (periodic grid).

        Solves the same discrete system the old Jacobi loop approximated, but in
        one FFT pair — divergence drops to ~machine epsilon, so vortices rotate
        and persist instead of diffusing. ``iters`` kept for API compatibility.
        """
        # Forward-difference divergence; backward-difference gradient (adjoint
        # pair) so D∘G is the standard 5-point Laplacian -> exact, no checkerboard.
        div = ((np.roll(self.u, -1, 1) - self.u) +
               (np.roll(self.v, -1, 0) - self.v))
        p_hat = -np.fft.fft2(div) / self._poisson    # L = -poisson eigenvalues
        p_hat[0, 0] = 0.0
        p = np.real(np.fft.ifft2(p_hat)).astype(np.float32)
        self.u -= (p - np.roll(p, 1, 1)).astype(np.float32)
        self.v -= (p - np.roll(p, 1, 0)).astype(np.float32)

    def _vorticity_confine(self, eps: float, dt: float) -> None:
        if eps <= 0:
            return
        curl = ((np.roll(self.v, -1, 1) - np.roll(self.v, 1, 1)) -
                (np.roll(self.u, -1, 0) - np.roll(self.u, 1, 0))) * 0.5
        absc = np.abs(curl)
        gx = (np.roll(absc, -1, 1) - np.roll(absc, 1, 1)) * 0.5
        gy = (np.roll(absc, -1, 0) - np.roll(absc, 1, 0)) * 0.5
        norm = np.sqrt(gx * gx + gy * gy) + 1e-5
        gx, gy = gx / norm, gy / norm
        self.u += eps * dt * (gy * curl)
        self.v += eps * dt * (-gx * curl)

    def add_force(self, fu: np.ndarray, fv: np.ndarray) -> None:
        self.u += fu.astype(np.float32)
        self.v += fv.astype(np.float32)

    def add_dye(self, px: float, py: float, radius: float,
                color: np.ndarray, amount: float) -> None:
        """Inject coloured dye (no velocity) — used by continuous emitters."""
        n = self.n
        r = max(1.0, radius * n)
        d2 = (self.xs - px * n) ** 2 + (self.ys - py * n) ** 2
        g = np.exp(-d2 / (2 * r * r)).astype(np.float32)
        self.density += (amount * g)[..., None] * color[None, None, :]

    def add_force_at(self, x: float, y: float, radius: float,
                     fx: float, fy: float) -> None:
        """Inject a localised directional velocity (no dye) — drives jets."""
        n = self.n
        r = max(1.0, radius * n)
        d2 = (self.xs - x * n) ** 2 + (self.ys - y * n) ** 2
        g = np.exp(-d2 / (2 * r * r)).astype(np.float32)
        self.u += (g * fx).astype(np.float32)
        self.v += (g * fy).astype(np.float32)

    def add_splat(self, px: float, py: float, radius: float, force: float,
                  color: np.ndarray, dir_angle: float) -> None:
        """Inject a Gaussian blob of velocity + colour at normalised (px, py)."""
        n = self.n
        cx, cy = px * n, py * n
        r = max(1.0, radius * n)
        d2 = (self.xs - cx) ** 2 + (self.ys - cy) ** 2
        g = np.exp(-d2 / (2 * r * r)).astype(np.float32)
        vel = g * force * FORCE_K / n
        self.u += (vel * np.cos(dir_angle)).astype(np.float32)
        self.v += (vel * np.sin(dir_angle)).astype(np.float32)
        self.density += g[..., None] * color[None, None, :]

    def step(self, dt: float, vort_eps: float) -> None:
        if self.viscosity > 0:
            k = self.viscosity
            self.u = (self.u + k * (np.roll(self.u, 1, 0) + np.roll(self.u, -1, 0) +
                      np.roll(self.u, 1, 1) + np.roll(self.u, -1, 1))) / (1 + 4 * k)
            self.v = (self.v + k * (np.roll(self.v, 1, 0) + np.roll(self.v, -1, 0) +
                      np.roll(self.v, 1, 1) + np.roll(self.v, -1, 1))) / (1 + 4 * k)
        self._vorticity_confine(vort_eps, dt)
        self._project()
        # Self-advect velocity (backtrace uses the pre-advection field), reproject.
        u0, v0 = self.u.copy(), self.v.copy()
        vel = np.stack([self.u, self.v], axis=-1).astype(np.float32)
        vel = self._advect(vel, u0, v0, dt)
        self.u = np.ascontiguousarray(vel[..., 0])
        self.v = np.ascontiguousarray(vel[..., 1])
        self._project()
        self.density = self._advect(self.density, self.u, self.v, dt)
        self.density *= self.dissipation
        np.clip(self.density, 0.0, 12.0, out=self.density)
        # Damp velocity so continuous ambient forcing reaches a steady state
        # instead of accumulating without bound.
        self.u *= self.vel_dissipation
        self.v *= self.vel_dissipation

    def kinetic_energy(self) -> float:
        return float(np.mean(self.u ** 2 + self.v ** 2))

    def total_density(self) -> float:
        return float(np.mean(self.density))


def _build_event_index(events, fps: int, n_frames: int) -> List[list]:
    by_frame: List[list] = [[] for _ in range(n_frames)]
    for e in events:
        fi = int(round(e.t * fps))
        if 0 <= fi < n_frames:
            by_frame[fi].append(e)
    return by_frame


def _lookahead_boost(score: Score, frame_i: int, fps: int, lookahead_s: float) -> float:
    """0..1 tension ramp in the ``lookahead_s`` window before a drop section."""
    if lookahead_s <= 0:
        return 0.0
    t = frame_i / fps
    boost = 0.0
    for s in score.sections:
        if s.label == "drop" and 0 <= (s.start - t) <= lookahead_s:
            boost = max(boost, 1.0 - (s.start - t) / lookahead_s)
    return boost


def simulate(score: Score, recipe: Recipe, out_dir: str | Path,
             max_frames: Optional[int] = None,
             progress: Optional[ProgressFn] = None,
             frame_configs: Optional[List[FluidConfig]] = None,
             render_range: Optional[tuple] = None,
             warmup_frames: int = 0,
             write_velocity: bool = True) -> SimResult:
    """Run the fluid sim. If ``frame_configs`` is given (one FluidConfig per
    frame), the *non-structural* parameters vary per frame — this is how a single
    continuous simulation takes different parameters per musical segment.

    ``render_range=(f0, f1)`` simulates only that window (plus ``warmup_frames``
    of unrendered lead-in so the state converges to what the full run would
    hold — dye and velocity memory are short), writing frames renumbered from 0.
    ``write_velocity=False`` skips the per-frame .npy dumps (previews don't need
    them; only E3/E4 do).
    """
    import imageio.v2 as imageio

    out_dir = Path(out_dir)
    fluid_dir = out_dir / "fluid"
    vel_dir = out_dir / "velocity"
    fluid_dir.mkdir(parents=True, exist_ok=True)
    if write_velocity:
        vel_dir.mkdir(parents=True, exist_ok=True)

    fps = score.audio.fps
    n_frames = score.n_frames if max_frames is None else min(score.n_frames, max_frames)
    if render_range is not None:
        render_start = max(0, int(render_range[0]))
        sim_end = min(n_frames, int(render_range[1]))
        sim_start = max(0, render_start - max(0, warmup_frames))
    else:
        render_start, sim_start, sim_end = 0, 0, n_frames
    base_fc = recipe.fluid               # structural params (resolution) come from here
    sim = FluidSim(base_fc.resolution, base_fc.dissipation, base_fc.viscosity,
                   recipe.seed, vel_dissipation=base_fc.velocity_dissipation)

    low_by_frame = _build_event_index(score.onsets.get("low", []), fps, sim_end)
    high_by_frame = _build_event_index(score.onsets.get("high", []), fps, sim_end)

    rng = np.random.default_rng(recipe.seed + 1)
    gx = sim.xs / base_fc.resolution
    gy = sim.ys / base_fc.resolution
    anchor = np.array([0.5, 0.5])           # centre of gravity for kicks
    dt = 1.0
    t_phase = 0.0                           # continuous ambient phase across segments
    stats = {"kinetic_energy": [], "total_density": []}
    sources: List[_Source] = []

    def spawn(x, y, color, cfg, mag, angle):
        """Birth a directional source: an initial jet along ``angle`` + ongoing
        directional emission, so matter streams away instead of pooling."""
        dx, dy = float(np.cos(angle)), float(np.sin(angle))
        impulse = cfg.force * FORCE_K / n * (0.5 + mag)
        sim.add_force_at(x, y, cfg.radius, dx * impulse, dy * impulse)
        sources.append(_Source(x=x, y=y, color=color, radius=cfg.radius,
                               emit=cfg.emit * (0.5 + mag),
                               life=max(1, int(cfg.lifetime_s * fps)),
                               drift=cfg.drift, dx=dx, dy=dy, speed=cfg.speed,
                               jet=JET_FRACTION * impulse))

    render_res = base_fc.render_resolution
    bloom_sigma = max(1.0, base_fc.resolution / 48)
    n = base_fc.resolution
    total_steps = sim_end - sim_start
    for step, i in enumerate(range(sim_start, sim_end)):
        # Per-frame (per-segment) parameters; structural params stay from base_fc.
        fc = frame_configs[i] if frame_configs is not None else base_fc
        sim.dissipation = fc.dissipation
        sim.vel_dissipation = fc.velocity_dissipation
        palette = [_hex_to_rgb(c) for c in (fc.palette or ["#B84A74"])]
        low_cfg = fc.splats.get("low")
        high_cfg = fc.splats.get("high")
        fdata = score.frames[i]
        rms = fdata.rms
        t = t_phase
        t_phase += fc.ambient_speed

        # Ambient stirring carries existing dye — RMS-driven, no colour injected.
        ua, va = _curl_noise(gx, gy, t, fc.ambient_scale)
        amp = fc.ambient_strength * (AMBIENT_FLOOR + (1.0 - AMBIENT_FLOOR) * rms)
        sim.add_force(ua * amp, va * amp)

        # Kicks: jets radiating OUTWARD from a slowly-wandering centre of gravity,
        # so matter streams away and disperses instead of pooling into a blob.
        wc = anchor + WANDER_AMP * np.array([np.sin(i * 0.045), np.cos(i * 0.037)])
        if low_cfg:
            for e in low_by_frame[i]:
                px, py = np.clip(wc + rng.normal(0, KICK_JITTER, 2), 0.05, 0.95)
                ang = np.arctan2(py - wc[1], px - wc[0]) + rng.normal(0, KICK_ANGLE_JITTER)
                spawn(float(px), float(py), palette[0], low_cfg, e.mag, float(ang))
        # Hats: small fast darts in random directions, popping everywhere.
        if high_cfg:
            for j, e in enumerate(high_by_frame[i][: high_cfg.max_per_beat]):
                px, py = rng.uniform(0.08, 0.92, 2)
                spawn(float(px), float(py), palette[(i + j) % len(palette)],
                      high_cfg, e.mag, float(rng.uniform(0, 2 * np.pi)))

        # Lookahead: faint drifting sources before a drop, building tension early.
        boost = _lookahead_boost(score, i, fps, fc.lookahead_s)
        if boost > 0 and i % 3 == 0:
            px, py = rng.uniform(0.2, 0.8, 2)
            la = SimpleNamespace(radius=0.08, force=1500.0 * boost, emit=0.10 * boost,
                                 lifetime_s=0.7, drift=0.6, speed=0.8)
            spawn(float(px), float(py), palette[0] * 0.6, la, 1.0,
                  float(rng.uniform(0, 2 * np.pi)))

        sources = _advance_sources(sim, sources, n)

        # RMS drives vorticity between recipe min/max (scaled to the velocity regime).
        vmin, vmax = fc.vorticity.min, fc.vorticity.max
        vort = (vmin + (vmax - vmin) * rms) * VORT_K
        sim.step(dt, vort)

        # Render only the requested window (warmup frames advance state silently).
        if i >= render_start:
            frame = _render_frame(sim.density, fc.exposure, fc.bloom, bloom_sigma,
                                  fc.background)
            if render_res != base_fc.resolution:
                frame = cv2.resize(frame, (render_res, render_res),
                                   interpolation=cv2.INTER_LINEAR)
            imageio.imwrite(fluid_dir / f"{i - render_start:06d}.png", frame)
            if write_velocity:
                np.save(vel_dir / f"{i - render_start:06d}.npy",
                        np.stack([sim.u, sim.v], axis=-1).astype(np.float32))
            stats["kinetic_energy"].append(round(sim.kinetic_energy(), 6))
            stats["total_density"].append(round(sim.total_density(), 6))
        if progress:
            progress(step + 1, total_steps)

    stats_path = out_dir / "fluid_stats.json"
    stats_path.write_text(json.dumps(stats))
    return SimResult(fluid_dir=fluid_dir, velocity_dir=vel_dir, stats_path=stats_path,
                     n_frames=sim_end - render_start, resolution=render_res)
