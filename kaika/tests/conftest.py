"""Shared fixtures: deterministic synthetic audio so tests need no asset files."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
import pytest


def synth_track(path: Path, sr: int = 22050, duration: float = 4.0,
                bpm: float = 120.0) -> Path:
    """Write a click track: low kicks on the beat, high hats on the off-beats.

    Beat period for 120 BPM is 0.5 s; hats land every 0.25 s. Energy ramps up
    in the second half so structural segmentation has something to find.
    """
    rng = np.random.default_rng(0)
    n = int(sr * duration)
    y = np.zeros(n, dtype=np.float32)
    beat_period = 60.0 / bpm

    def burst(center_s, freq, dur=0.05, amp=0.8, noise=False):
        start = int(center_s * sr)
        length = int(dur * sr)
        if start >= n:
            return
        end = min(n, start + length)
        t = np.arange(end - start) / sr
        env = np.exp(-t * 40.0)
        if noise:
            band = rng.standard_normal(end - start).astype(np.float32)
            sig = band * env * amp
        else:
            sig = np.sin(2 * np.pi * freq * t).astype(np.float32) * env * amp
        y[start:end] += sig

    t = 0.0
    while t < duration:
        ramp = 0.4 + 0.6 * (t / duration)        # energy grows over the track
        burst(t, 60.0, dur=0.08, amp=0.9 * ramp)          # kick (low)
        burst(t + beat_period / 2, 6000.0, dur=0.03, amp=0.5 * ramp, noise=True)  # hat (high)
        t += beat_period

    y = np.clip(y, -1.0, 1.0)
    sf.write(str(path), y, sr)
    return path


@pytest.fixture
def track_wav(tmp_path) -> Path:
    return synth_track(tmp_path / "track.wav")
