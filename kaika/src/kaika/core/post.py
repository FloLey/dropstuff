"""E5 — Post-production.  styled frames + audio -> final.mp4.

Optional RIFE-style interpolation and upscaling (here via ffmpeg fallbacks;
true RIFE / Real-ESRGAN are drop-in replacements), aspect framing, and audio
mux. The automatic sync check correlates the audio RMS envelope against the
*fluid* kinetic energy (deterministically audio-driven) rather than styled-frame
luminance, which depends too much on prompt/palette.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

from .score import Score
from .media import run_ffmpeg, _EVEN

ASPECT_FILTERS = {
    "square": None,
    "wide": "scale=trunc(iw/2)*2:trunc(ih/2)*2,"
            "pad=ih*16/9:ih:(ow-iw)/2:0:black,setsar=1",
}


@dataclass
class SyncResult:
    lag_frames: int           # best-correlation offset (frames). 0 == in sync
    correlation: float        # peak normalised cross-correlation, -1..1


@dataclass
class PostResult:
    output: Path
    sync: Optional[SyncResult]


def _normish(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    x = x - x.mean()
    s = x.std()
    return x / s if s > 1e-9 else x


def sync_check(score: Score, fluid_stats: dict, max_lag: int = 6) -> SyncResult:
    """Cross-correlate audio RMS with fluid kinetic energy to detect drift."""
    rms = np.array([f.rms for f in score.frames], dtype=np.float64)
    ke = np.array(fluid_stats.get("kinetic_energy", []), dtype=np.float64)
    n = min(len(rms), len(ke))
    if n < 4:
        return SyncResult(lag_frames=0, correlation=0.0)
    a, b = _normish(rms[:n]), _normish(ke[:n])
    best_lag, best_corr = 0, -2.0
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            x, y = a[-lag:], b[: n + lag]
        else:
            x, y = a[: n - lag], b[lag:]
        if len(x) < 4:
            continue
        c = float(np.corrcoef(x, y)[0, 1]) if x.std() and y.std() else 0.0
        if c > best_corr:
            best_corr, best_lag = c, lag
    return SyncResult(lag_frames=best_lag, correlation=round(best_corr, 4))


def assemble(frames_dir: str | Path, audio_path: str | Path, out_path: str | Path,
             fps: int, aspect: str = "square", interpolate: bool = False,
             upscale: bool = False, upscale_to: int = 2048,
             pattern: str = "%06d.png",
             score: Optional[Score] = None,
             fluid_stats_path: Optional[str | Path] = None) -> PostResult:
    frames_dir = Path(frames_dir)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    vf: List[str] = []
    if upscale:
        vf.append(f"scale={upscale_to}:-2:flags=lanczos")
    if interpolate:
        vf.append(f"minterpolate=fps={fps * 2}:mi_mode=mci")
        out_fps = fps * 2
    else:
        out_fps = fps
    aspect_filter = ASPECT_FILTERS.get(aspect)
    vf.append(aspect_filter if aspect_filter else _EVEN)

    args = ["-framerate", str(fps), "-i", str(frames_dir / pattern)]
    if Path(audio_path).exists():
        args += ["-i", str(audio_path)]
    args += ["-vf", ",".join(vf), "-r", str(out_fps),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18"]
    if Path(audio_path).exists():
        args += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    args += [str(out_path)]
    run_ffmpeg(args)

    sync = None
    if score is not None and fluid_stats_path and Path(fluid_stats_path).exists():
        sync = sync_check(score, json.loads(Path(fluid_stats_path).read_text()))

    return PostResult(output=out_path, sync=sync)
