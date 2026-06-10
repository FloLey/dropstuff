"""Phase S1: segment-aware Project model + per-segment simulation."""
from __future__ import annotations

import json

import numpy as np

from kaika.core.analyze import analyze
from kaika.core import recipe as R
from kaika.core.project import Project, Segment, _deep_merge
from kaika.core.simulate import simulate


def test_from_score_builds_segments(track_wav):
    score = analyze(track_wav, fps=24)
    rec = R.load_recipe("eclosion")
    proj = Project.from_score(score, rec, audio="track.wav")
    assert len(proj.segments) == len(score.sections)
    # prompts seeded from the recipe per label
    assert proj.segments[0].prompt == rec.prompt_for(score.sections[0].label)
    assert proj.fps == 24


def test_deep_merge_partial_override():
    base = {"vorticity": {"min": 8, "max": 38}, "dissipation": 0.9}
    out = _deep_merge(base, {"vorticity": {"max": 60}})
    assert out["vorticity"] == {"min": 8, "max": 60}   # min preserved
    assert out["dissipation"] == 0.9


def test_frame_configs_apply_segment_overrides(track_wav):
    score = analyze(track_wav, fps=24)
    rec = R.from_dict({"fluid": {"vorticity": {"min": 8, "max": 38}}})
    proj = Project.from_score(score, rec, audio="t.wav")
    # override the last segment only
    proj.segments[-1].fluid = {"vorticity": {"max": 99}}
    cfgs = proj.frame_configs(score.n_frames)
    assert cfgs[0].vorticity.max == 38           # early frame: base
    assert cfgs[-1].vorticity.max == 99          # last segment: overridden
    assert cfgs[0].vorticity.min == 8            # partial override kept min


def test_prompt_schedule_per_segment(track_wav):
    score = analyze(track_wav, fps=24)
    rec = R.load_recipe("eclosion")
    proj = Project.from_score(score, rec, audio="t.wav")
    proj.segments[-1].prompt = "UNIQUE LAST PROMPT"
    sched = proj.prompt_schedule(score.n_frames)
    assert len(sched) == score.n_frames
    assert sched[-1] == "UNIQUE LAST PROMPT"


def test_roundtrip(tmp_path, track_wav):
    score = analyze(track_wav, fps=24)
    rec = R.load_recipe("eclosion")
    proj = Project.from_score(score, rec, audio="t.wav")
    proj.segments[0].fluid = {"dissipation": 0.85}
    p = tmp_path / "project.json"
    proj.to_json(p)
    again = Project.from_json(p)
    assert len(again.segments) == len(proj.segments)
    assert again.segments[0].fluid == {"dissipation": 0.85}
    assert again.recipe.seed == proj.recipe.seed


def test_simulation_respects_per_segment_emit(track_wav, tmp_path):
    """A segment that emits no dye must stay darker than one that does — proof
    that per-segment parameters actually drive the continuous simulation."""
    score = analyze(track_wav, fps=24)
    half = score.audio.duration_s / 2
    rec = R.from_dict({"seed": 1, "fluid": {"resolution": 48, "render_resolution": 48}})
    proj = Project(audio="t.wav", recipe=rec, fps=24, segments=[
        Segment(start=0.0, end=half, label="silent",
                fluid={"splats": {"low": {"radius": 0.12, "force": 9000,
                                          "placement": "anchored", "emit": 0.0},
                                  "high": {"radius": 0.03, "force": 3500,
                                           "placement": "scatter", "emit": 0.0}},
                       "ambient_strength": 0.0}),
        Segment(start=half, end=score.audio.duration_s, label="loud", fluid={}),
    ])
    n = score.n_frames
    cfgs = proj.frame_configs(n)
    sim = simulate(score, rec, tmp_path, frame_configs=cfgs)
    import imageio.v2 as imageio
    frames = sorted(sim.fluid_dir.glob("*.png"))
    h = len(frames) // 2
    first = np.mean([imageio.imread(f).mean() for f in frames[:h]])
    second = np.mean([imageio.imread(f).mean() for f in frames[h:]])
    assert first < second        # silent segment darker than the emitting one
