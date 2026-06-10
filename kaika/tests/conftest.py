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
            from scipy.signal import butter, sosfilt
            band = rng.standard_normal(end - start).astype(np.float32)
            # high-pass the burst like a real hi-hat, so it is genuinely a
            # high-band event and not broadband noise leaking into the low band
            sos = butter(4, 5000.0, btype="high", fs=sr, output="sos")
            band = sosfilt(sos, band).astype(np.float32)
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


# --- shared server-test scaffolding ----------------------------------------
import time as _time

# A fast, GPU-free recipe for end-to-end server/pipeline tests.
SMALL_RECIPE = {
    "name": "t", "seed": 1,
    "fluid": {"resolution": 40, "render_resolution": 40},
    "diffusion": {"backend": "local", "control": ["depth"]},
    "post": {"fps": 24},
}


@pytest.fixture
def api_client(tmp_path):
    """A TestClient over a fresh app with isolated runs/ and data/ dirs."""
    from fastapi.testclient import TestClient
    from kaika.server.app import create_app
    app = create_app(runs_root=tmp_path / "runs", data_dir=tmp_path / "data")
    with TestClient(app) as c:
        yield c


def upload_audio(client, tmp_path, duration=1.0) -> str:
    """Synthesize, upload, and return the audio_id."""
    wav = synth_track(tmp_path / "upload.wav", duration=duration)
    with wav.open("rb") as f:
        r = client.post("/api/upload", files={"file": ("upload.wav", f, "audio/wav")})
    assert r.status_code == 200
    return r.json()["audio_id"]


def wait_for_job(client, job_id, timeout=90) -> dict:
    """Poll a job until it finishes (done/error) or the timeout elapses."""
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            return j
        _time.sleep(0.2)
    raise AssertionError("job did not finish in time")
