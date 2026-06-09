"""E3 — Control signals.  fluid + velocity -> depth / canny / flow.

The unfair advantage of a simulation over filmed video: we estimate nothing.
The density field *is* the depth map; the velocity field *is* the optical flow.
Both are ground truth, frame-aligned with the fluid by construction.

Outputs, per run dir:
  control/depth/%06d.png   8-bit depth (normalised density)
  control/canny/%06d.png   edges of the density field
  control/flow/%06d.png    HSV-coloured exact optical flow
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

import numpy as np
import cv2

ProgressFn = Callable[[int, int], None]
ALL_SIGNALS = ("depth", "canny", "flow")


@dataclass
class ControlResult:
    dirs: dict          # signal name -> Path
    n_frames: int


def _luma(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def _depth(rgb: np.ndarray) -> np.ndarray:
    g = _luma(rgb).astype(np.float32)
    lo, hi = float(g.min()), float(g.max())
    if hi - lo < 1e-6:
        return np.zeros_like(g, np.uint8)
    return ((g - lo) / (hi - lo) * 255).astype(np.uint8)


def _canny(rgb: np.ndarray) -> np.ndarray:
    g = _luma(rgb)
    return cv2.Canny(g, 50, 150)


def _flow_rgb(vel: np.ndarray, size: int) -> np.ndarray:
    """Colour-code a velocity field (H,W,2) as HSV flow at the render size."""
    u, v = vel[..., 0], vel[..., 1]
    mag = np.sqrt(u * u + v * v)
    ang = np.arctan2(v, u)                  # -pi..pi
    hsv = np.zeros((*u.shape, 3), np.uint8)
    hsv[..., 0] = ((ang + np.pi) / (2 * np.pi) * 179).astype(np.uint8)   # hue
    hsv[..., 1] = 255
    peak = float(mag.max())
    val = (mag / peak * 255).astype(np.uint8) if peak > 1e-6 else np.zeros_like(u, np.uint8)
    hsv[..., 2] = val
    rgb = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    if rgb.shape[0] != size:
        rgb = cv2.resize(rgb, (size, size), interpolation=cv2.INTER_LINEAR)
    return rgb


def generate_control(fluid_dir: str | Path, velocity_dir: str | Path,
                     out_dir: str | Path,
                     signals: Sequence[str] = ALL_SIGNALS,
                     render_resolution: Optional[int] = None,
                     progress: Optional[ProgressFn] = None) -> ControlResult:
    import imageio.v2 as imageio

    fluid_dir = Path(fluid_dir)
    velocity_dir = Path(velocity_dir)
    out_dir = Path(out_dir)
    signals = [s for s in signals if s in ALL_SIGNALS]

    dirs = {s: out_dir / "control" / s for s in signals}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    frames = sorted(fluid_dir.glob("*.png"))
    n = len(frames)
    for i, fp in enumerate(frames):
        rgb = imageio.imread(fp)[..., :3]
        size = render_resolution or rgb.shape[0]
        if "depth" in dirs:
            imageio.imwrite(dirs["depth"] / fp.name, _depth(rgb))
        if "canny" in dirs:
            imageio.imwrite(dirs["canny"] / fp.name, _canny(rgb))
        if "flow" in dirs:
            vp = velocity_dir / (fp.stem + ".npy")
            vel = np.load(vp) if vp.exists() else np.zeros((size, size, 2), np.float32)
            imageio.imwrite(dirs["flow"] / fp.name, _flow_rgb(vel, size))
        if progress:
            progress(i + 1, n)

    return ControlResult(dirs=dirs, n_frames=n)
