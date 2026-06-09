"""Phase 3: E3 control signals."""
from __future__ import annotations

import numpy as np
import imageio.v2 as imageio

from kaika.core.analyze import analyze
from kaika.core import recipe as R
from kaika.core.simulate import simulate
from kaika.core.control import generate_control, ALL_SIGNALS


def _prep(track_wav, tmp_path, frames=8):
    score = analyze(track_wav, fps=24)
    rec = R.from_dict({"seed": 3, "fluid": {"resolution": 48, "render_resolution": 64}})
    sim = simulate(score, rec, tmp_path, max_frames=frames)
    return sim


def test_all_signals_written_and_aligned(track_wav, tmp_path):
    sim = _prep(track_wav, tmp_path)
    res = generate_control(sim.fluid_dir, sim.velocity_dir, tmp_path)
    assert set(res.dirs) == set(ALL_SIGNALS)
    for d in res.dirs.values():
        assert len(list(d.glob("*.png"))) == sim.n_frames == res.n_frames


def test_depth_is_grayscale_with_range(track_wav, tmp_path):
    sim = _prep(track_wav, tmp_path)
    res = generate_control(sim.fluid_dir, sim.velocity_dir, tmp_path, signals=["depth"])
    img = imageio.imread(sorted(res.dirs["depth"].glob("*.png"))[-1])
    assert img.ndim == 2                  # single channel
    assert int(img.max()) > int(img.min())  # real depth gradient, not flat


def test_canny_is_binary(track_wav, tmp_path):
    sim = _prep(track_wav, tmp_path)
    res = generate_control(sim.fluid_dir, sim.velocity_dir, tmp_path, signals=["canny"])
    img = imageio.imread(sorted(res.dirs["canny"].glob("*.png"))[-1])
    assert set(np.unique(img)).issubset({0, 255})


def test_flow_matches_render_size(track_wav, tmp_path):
    sim = _prep(track_wav, tmp_path)
    res = generate_control(sim.fluid_dir, sim.velocity_dir, tmp_path,
                           signals=["flow"], render_resolution=64)
    img = imageio.imread(sorted(res.dirs["flow"].glob("*.png"))[-1])
    assert img.shape == (64, 64, 3)
    assert img.max() > 0                  # there is motion to colour
