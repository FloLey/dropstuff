"""Phase 4: E5 post-production + media helpers."""
from __future__ import annotations

import json

import numpy as np

from kaika.core.analyze import analyze
from kaika.core import recipe as R
from kaika.core.simulate import simulate
from kaika.core.post import assemble, sync_check
from kaika.core.media import frames_to_video, video_to_frames


def _sim(track_wav, tmp_path, frames=16):
    score = analyze(track_wav, fps=24)
    rec = R.from_dict({"seed": 5, "fluid": {"resolution": 48, "render_resolution": 64}})
    return score, simulate(score, rec, tmp_path, max_frames=frames)


def test_assemble_produces_playable_mp4(track_wav, tmp_path):
    score, sim = _sim(track_wav, tmp_path)
    out = tmp_path / "final.mp4"
    res = assemble(sim.fluid_dir, track_wav, out, fps=24,
                   score=score, fluid_stats_path=sim.stats_path)
    assert out.exists() and out.stat().st_size > 1000
    assert res.sync is not None
    assert -6 <= res.sync.lag_frames <= 6


def test_assemble_without_audio(track_wav, tmp_path):
    _, sim = _sim(track_wav, tmp_path, frames=8)
    out = tmp_path / "noaudio.mp4"
    assemble(sim.fluid_dir, tmp_path / "missing.wav", out, fps=24)
    assert out.exists()


def test_wide_aspect(track_wav, tmp_path):
    _, sim = _sim(track_wav, tmp_path, frames=8)
    out = tmp_path / "wide.mp4"
    assemble(sim.fluid_dir, tmp_path / "no.wav", out, fps=24, aspect="wide")
    # probe first frame via the bundled-ffmpeg reader to confirm 16:9-ish output
    import imageio.v2 as imageio
    reader = imageio.get_reader(str(out))
    frame = reader.get_data(0)
    reader.close()
    h, w = frame.shape[:2]
    assert abs((w / h) - 16 / 9) < 0.05


def test_sync_check_aligned_signal():
    """A fluid energy curve equal to RMS should report ~zero lag, high corr."""
    from kaika.core.score import Score, AudioInfo, FrameData
    frames = [FrameData(rms=float(r), centroid_hz=1000, bands=[0.5, 0.3, 0.2])
              for r in np.abs(np.sin(np.linspace(0, 6, 40)))]
    score = Score(audio=AudioInfo(sr=22050, duration_s=40 / 24, fps=24, hop_length=918),
                  tempo_bpm=120.0, frames=frames)
    stats = {"kinetic_energy": [f.rms for f in frames]}
    res = sync_check(score, stats)
    assert res.lag_frames == 0
    assert res.correlation > 0.95


def test_media_video_roundtrip(track_wav, tmp_path):
    """Transfer-compression path: frames -> video -> frames."""
    _, sim = _sim(track_wav, tmp_path, frames=10)
    vid = frames_to_video(sim.fluid_dir, tmp_path / "transfer.mp4", fps=24)
    assert vid.exists()
    out = video_to_frames(vid, tmp_path / "restored")
    restored = sorted(out.glob("*.png"))
    assert len(restored) == 10
