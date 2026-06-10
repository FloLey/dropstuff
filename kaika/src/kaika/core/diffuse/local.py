"""Local, GPU-free diffuser fallback.

A deterministic stylizer that runs anywhere so the *whole* pipeline produces a
clip with no GPU. It is not the figurative metamorphosis (that needs the
ComfyUI/Wan backend) — it is a faithful drop-in honouring the E3->E4 interface:
it reads fluid + control frames, respects the fluid structure, and applies a
bloom/colour-grade pass blended by ``diffusion.strength``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import cv2

from .base import Diffuser, DiffuseRequest, DiffuseResult, ProgressFn


FLOW_TEX_GAIN = 0.35       # how strongly the advected texture modulates output
FLOW_TEX_REFRESH = 0.06    # fresh noise blended in per frame (keeps detail alive)
FLOW_TEX_STEP = 3.0        # advection step in texture pixels per unit velocity


class _FlowTexture:
    """A noise field advected by the simulation's exact velocity.

    Accumulating advection turns isotropic noise into fine streaks *along* the
    flow (a cheap line-integral-convolution), giving the styled frames organic
    filament detail that moves exactly with the fluid.
    """

    def __init__(self, size: int, seed: int):
        self.rng = np.random.default_rng(seed)
        self.size = size
        self.tex = self.rng.random((size, size), dtype=np.float32)
        ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
        self.xs, self.ys = xs, ys

    def step(self, vel: Optional[np.ndarray]) -> np.ndarray:
        if vel is not None:
            u = cv2.resize(vel[..., 0], (self.size, self.size))
            v = cv2.resize(vel[..., 1], (self.size, self.size))
            mx = self.xs - FLOW_TEX_STEP * u
            my = self.ys - FLOW_TEX_STEP * v
            self.tex = cv2.remap(self.tex, mx, my, cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_WRAP)
        fresh = self.rng.random((self.size, self.size), dtype=np.float32)
        self.tex = (1 - FLOW_TEX_REFRESH) * self.tex + FLOW_TEX_REFRESH * fresh
        return self.tex


class LocalStylizer(Diffuser):
    name = "local"

    def _stylize(self, fluid: np.ndarray, depth: Optional[np.ndarray],
                 strength: float, tex: Optional[np.ndarray] = None) -> np.ndarray:
        f = fluid.astype(np.float32) / 255.0
        # Bloom: blurred highlights added back for a soft, blooming glow.
        bright = np.clip(f - 0.45, 0, 1)
        bloom = cv2.GaussianBlur(bright, (0, 0), sigmaX=max(1.0, f.shape[0] / 64))
        styled = f + 1.6 * bloom
        # Depth-modulated contrast so denser regions read as foreground.
        if depth is not None:
            d = cv2.resize(depth, (f.shape[1], f.shape[0])).astype(np.float32) / 255.0
            styled *= (0.6 + 0.8 * d[..., None])
        # Flow-advected texture: fine streaks along the motion, weighted by
        # brightness so the dark background stays clean.
        if tex is not None:
            luma = styled.mean(axis=2, keepdims=True)
            styled *= 1.0 + FLOW_TEX_GAIN * (tex[..., None] - 0.5) * np.clip(luma * 2, 0, 1)
        # Gentle S-curve + saturation lift.
        styled = np.clip(styled, 0, 1)
        styled = styled ** 0.85
        hsv = cv2.cvtColor((styled * 255).astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
        hsv[..., 1] = np.clip(hsv[..., 1] * 1.25, 0, 255)
        styled = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB).astype(np.float32) / 255.0
        # Blend by strength: low strength stays near the raw fluid.
        out = (1 - strength) * f + strength * styled
        return (np.clip(out, 0, 1) * 255).astype(np.uint8)

    def run(self, req: DiffuseRequest,
            progress: Optional[ProgressFn] = None) -> DiffuseResult:
        import imageio.v2 as imageio

        styled_dir = req.out_dir / "styled"
        styled_dir.mkdir(parents=True, exist_ok=True)
        depth_dir = req.control_dirs.get("depth")
        velocity_dir = req.fluid_dir.parent / "velocity"   # run-dir layout
        strength = float(req.recipe.diffusion.strength)

        frames = sorted(req.fluid_dir.glob("*.png"))[: req.n_frames]
        flow_tex: Optional[_FlowTexture] = None
        for i, fp in enumerate(frames):
            fluid = imageio.imread(fp)[..., :3]
            depth = None
            if depth_dir is not None and (depth_dir / fp.name).exists():
                depth = imageio.imread(depth_dir / fp.name)
            if flow_tex is None:
                flow_tex = _FlowTexture(fluid.shape[0], req.recipe.seed)
            vp = velocity_dir / (fp.stem + ".npy")
            tex = flow_tex.step(np.load(vp) if vp.exists() else None)
            out = self._stylize(fluid, depth, strength, tex)
            imageio.imwrite(styled_dir / fp.name, out)
            if progress:
                progress(i + 1, len(frames))

        return DiffuseResult(styled_dir=styled_dir, n_frames=len(frames),
                             backend=self.name)
