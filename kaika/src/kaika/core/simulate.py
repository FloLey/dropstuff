"""E2 — Fluid simulation.  score + recipe -> fluid frames + velocity fields.

A Jos-Stam style stable-fluids solver (incompressible Navier-Stokes) in pure
NumPy with toroidal boundaries, so it is fully deterministic (seed -> identical
video) and runs anywhere with no GPU. The simulation is the *movement skeleton*:
audio onsets inject splats, RMS drives vorticity, and an upcoming drop is
anticipated by sub-visible vortices (lookahead).

Outputs, per run dir:
  fluid/%06d.png        RGB density frame (render_resolution)
  velocity/%06d.npy     (H, W, 2) float32 velocity field (sim resolution)
  fluid_stats.json      per-frame kinetic energy + density (for E5 sync check)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np
import cv2

from .score import Score
from .recipe import Recipe

ProgressFn = Callable[[int, int], None]


def _hue_to_rgb(hue: np.ndarray) -> np.ndarray:
    """Vectorised HSV(h, 1, 1) -> RGB for a hue array in [0, 1]."""
    h6 = (hue % 1.0) * 6.0
    i = np.floor(h6).astype(int)
    f = h6 - i
    p = np.zeros_like(hue)
    q = 1.0 - f
    t = f
    r = np.choose(i % 6, [1, q, p, p, t, 1.0 * np.ones_like(hue)])
    g = np.choose(i % 6, [t, 1.0 * np.ones_like(hue), 1, q, p, p])
    b = np.choose(i % 6, [p, p, t, 1.0 * np.ones_like(hue), 1, q])
    return np.stack([r, g, b], axis=-1)


def _centroid_to_hue(centroid_hz: float) -> float:
    """Map spectral centroid to a hue: low->magenta/pink, high->teal/cyan."""
    lo, hi = np.log10(150.0), np.log10(8000.0)
    x = (np.log10(max(centroid_hz, 150.0)) - lo) / (hi - lo)
    x = float(np.clip(x, 0.0, 1.0))
    return 0.92 - 0.42 * x          # 0.92 (magenta) -> 0.50 (teal/cyan)


@dataclass
class SimResult:
    fluid_dir: Path
    velocity_dir: Path
    stats_path: Path
    n_frames: int
    resolution: int


class FluidSim:
    """Toroidal stable-fluids solver on an NxN grid."""

    def __init__(self, n: int, dissipation: float, viscosity: float, seed: int):
        self.n = n
        self.dissipation = dissipation
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
        """MacCormack advection (cubic semi-Lagrangian + error correction).

        Two cubic backtraces with a corrector pass remove most numerical
        diffusion, keeping crisp filaments; a min/max limiter clamps overshoot.
        Handles 1- or multi-channel fields in a single ``cv2.remap`` call.
        """
        mx = (self.xs - dt * u).astype(np.float32)
        my = (self.ys - dt * v).astype(np.float32)
        fwd = cv2.remap(field, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_WRAP)
        bx = (self.xs + dt * u).astype(np.float32)
        by = (self.ys + dt * v).astype(np.float32)
        back = cv2.remap(fwd, bx, by, cv2.INTER_CUBIC, borderMode=cv2.BORDER_WRAP)
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

    def add_splat(self, px: float, py: float, radius: float, force: float,
                  color: np.ndarray, dir_angle: float) -> None:
        """Inject a Gaussian blob of velocity + colour at normalised (px, py)."""
        n = self.n
        cx, cy = px * n, py * n
        r = max(1.0, radius * n)
        d2 = (self.xs - cx) ** 2 + (self.ys - cy) ** 2
        g = np.exp(-d2 / (2 * r * r)).astype(np.float32)
        self.u += (g * force * np.cos(dir_angle) / n).astype(np.float32)
        self.v += (g * force * np.sin(dir_angle) / n).astype(np.float32)
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
        np.clip(self.density, 0.0, 4.0, out=self.density)

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
             progress: Optional[ProgressFn] = None) -> SimResult:
    import imageio.v2 as imageio

    out_dir = Path(out_dir)
    fluid_dir = out_dir / "fluid"
    vel_dir = out_dir / "velocity"
    fluid_dir.mkdir(parents=True, exist_ok=True)
    vel_dir.mkdir(parents=True, exist_ok=True)

    fps = score.audio.fps
    n_frames = score.n_frames if max_frames is None else min(score.n_frames, max_frames)
    fc = recipe.fluid
    sim = FluidSim(fc.resolution, fc.dissipation, fc.viscosity, recipe.seed)

    low_cfg = fc.splats.get("low")
    high_cfg = fc.splats.get("high")
    low_by_frame = _build_event_index(score.onsets.get("low", []), fps, n_frames)
    high_by_frame = _build_event_index(score.onsets.get("high", []), fps, n_frames)

    rng = np.random.default_rng(recipe.seed + 1)
    anchor = np.array([0.5, 0.5])           # centre of gravity for kicks
    dt = 1.0
    stats = {"kinetic_energy": [], "total_density": []}

    render_res = fc.render_resolution
    for i in range(n_frames):
        fdata = score.frames[i]
        hue = _centroid_to_hue(fdata.centroid_hz)
        color = _hue_to_rgb(np.array([hue]))[0].astype(np.float32)

        # Kicks: large, slow, anchored splats.
        if low_cfg:
            for e in low_by_frame[i]:
                jitter = rng.normal(0, 0.04, 2)
                px, py = np.clip(anchor + jitter, 0.05, 0.95)
                ang = rng.uniform(0, 2 * np.pi)
                sim.add_splat(px, py, low_cfg.radius, low_cfg.force * (0.4 + e.mag),
                              color * 1.2, ang)
        # Hats: small, vivid, scattered "pop everywhere".
        if high_cfg:
            hats = high_by_frame[i][: high_cfg.max_per_beat]
            for e in hats:
                px, py = rng.uniform(0.08, 0.92, 2)
                ang = rng.uniform(0, 2 * np.pi)
                sim.add_splat(px, py, high_cfg.radius, high_cfg.force * (0.4 + e.mag),
                              color, ang)

        # Lookahead: sub-visible swirl building tension before a drop.
        boost = _lookahead_boost(score, i, fps, fc.lookahead_s)
        if boost > 0:
            for _ in range(2):
                px, py = rng.uniform(0.2, 0.8, 2)
                ang = rng.uniform(0, 2 * np.pi)
                sim.add_splat(px, py, 0.10, 1200.0 * boost, color * 0.15 * boost, ang)

        # RMS drives vorticity between recipe min/max.
        vmin, vmax = fc.vorticity.min, fc.vorticity.max
        vort = vmin + (vmax - vmin) * fdata.rms
        sim.step(dt, vort)

        # Render frame.
        img = np.clip(sim.density, 0.0, 1.0)
        frame = (img * 255).astype(np.uint8)
        if render_res != fc.resolution:
            frame = cv2.resize(frame, (render_res, render_res),
                               interpolation=cv2.INTER_LINEAR)
        imageio.imwrite(fluid_dir / f"{i:06d}.png", frame)
        np.save(vel_dir / f"{i:06d}.npy",
                np.stack([sim.u, sim.v], axis=-1).astype(np.float32))

        stats["kinetic_energy"].append(round(sim.kinetic_energy(), 6))
        stats["total_density"].append(round(sim.total_density(), 6))
        if progress:
            progress(i + 1, n_frames)

    stats_path = out_dir / "fluid_stats.json"
    stats_path.write_text(json.dumps(stats))
    return SimResult(fluid_dir=fluid_dir, velocity_dir=vel_dir, stats_path=stats_path,
                     n_frames=n_frames, resolution=render_res)
