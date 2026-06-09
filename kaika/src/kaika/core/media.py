"""ffmpeg helpers shared by E5 (assembly) and E4 (compressed GPU transfer).

We never ship the system ffmpeg; the binary bundled with ``imageio-ffmpeg`` is
used so the package is self-contained. Frame sequences are packed into video
containers for remote transfer (the recommendation from review: thousands of
PNGs for a 3-min clip is gigabytes — a near-lossless video is a fraction).
"""
from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path
from typing import List


@lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: List[str]) -> None:
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{' '.join(cmd)}\n{proc.stderr}")


_EVEN = "scale=trunc(iw/2)*2:trunc(ih/2)*2"


def frames_to_video(frames_dir: str | Path, out_path: str | Path, fps: int,
                    near_lossless: bool = True, pattern: str = "%06d.png") -> Path:
    """Pack a frame sequence into an MP4 for compact transfer/extraction."""
    crf = "10" if near_lossless else "20"
    run_ffmpeg([
        "-framerate", str(fps), "-i", str(Path(frames_dir) / pattern),
        "-c:v", "libx264", "-preset", "fast", "-crf", crf,
        "-pix_fmt", "yuv444p" if near_lossless else "yuv420p",
        "-vf", _EVEN, str(out_path),
    ])
    return Path(out_path)


def video_to_frames(video_path: str | Path, out_dir: str | Path,
                    pattern: str = "%06d.png") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-i", str(video_path), "-start_number", "0", str(out_dir / pattern)])
    return out_dir
