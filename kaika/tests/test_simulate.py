"""Phase 2: E2 fluid simulation."""
from __future__ import annotations

import json

import numpy as np

from kaika.core.analyze import analyze
from kaika.core import recipe as R
from kaika.core.simulate import simulate, FluidSim


def _small_recipe():
    return R.from_dict({
        "name": "test", "seed": 7,
        "fluid": {"resolution": 48, "render_resolution": 64},
    })


def test_outputs_written(track_wav, tmp_path):
    score = analyze(track_wav, fps=24)
    res = simulate(score, _small_recipe(), tmp_path, max_frames=10)
    pngs = sorted(res.fluid_dir.glob("*.png"))
    npys = sorted(res.velocity_dir.glob("*.npy"))
    assert len(pngs) == 10 == len(npys) == res.n_frames
    v = np.load(npys[0])
    assert v.shape == (48, 48, 2)        # velocity at sim resolution
    assert v.dtype == np.float32


def test_render_resolution(track_wav, tmp_path):
    import imageio.v2 as imageio
    score = analyze(track_wav, fps=24)
    res = simulate(score, _small_recipe(), tmp_path, max_frames=4)
    img = imageio.imread(res.fluid_dir / "000003.png")
    assert img.shape[:2] == (64, 64)     # upsampled render


def test_density_appears(track_wav, tmp_path):
    score = analyze(track_wav, fps=24)
    res = simulate(score, _small_recipe(), tmp_path, max_frames=12)
    import imageio.v2 as imageio
    last = imageio.imread(sorted(res.fluid_dir.glob("*.png"))[-1])
    assert last.max() > 0   # splats injected colour, frame is not black


def test_stats_for_sync_check(track_wav, tmp_path):
    score = analyze(track_wav, fps=24)
    res = simulate(score, _small_recipe(), tmp_path, max_frames=8)
    stats = json.loads(res.stats_path.read_text())
    assert len(stats["kinetic_energy"]) == 8
    assert len(stats["total_density"]) == 8


def test_deterministic(track_wav, tmp_path):
    score = analyze(track_wav, fps=24)
    a = simulate(score, _small_recipe(), tmp_path / "a", max_frames=6)
    b = simulate(score, _small_recipe(), tmp_path / "b", max_frames=6)
    fa = np.load(sorted(a.velocity_dir.glob("*.npy"))[-1])
    fb = np.load(sorted(b.velocity_dir.glob("*.npy"))[-1])
    assert np.array_equal(fa, fb)        # same seed -> identical fields


def _divergence(u, v):
    return ((np.roll(u, -1, 1) - np.roll(u, 1, 1)) +
            (np.roll(v, -1, 0) - np.roll(v, 1, 0))) * 0.5


def _project_div(seed_force_args, iters):
    sim = FluidSim(n=32, dissipation=0.99, viscosity=0.0, seed=1)
    sim.add_splat(*seed_force_args)
    sim._project(iters=iters)
    return np.abs(_divergence(sim.u, sim.v)).mean()


def test_projection_converges():
    """The pressure solve must monotonically reduce divergence as the Poisson
    solver iterates — proof it is actually solving for incompressibility."""
    args = (0.5, 0.5, 0.1, 8000.0, np.array([1.0, 0.2, 0.5]), 0.7)
    sim = FluidSim(n=32, dissipation=0.99, viscosity=0.0, seed=1)
    sim.add_splat(*args)
    before = np.abs(_divergence(sim.u, sim.v)).mean()
    d_few = _project_div(args, iters=5)
    d_many = _project_div(args, iters=120)
    assert d_few < before          # any projection reduces divergence
    assert d_many < d_few          # more iterations -> closer to divergence-free
