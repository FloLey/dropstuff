"""Regression tests for PR #2 review fixes."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from kaika.server.app import create_app
from kaika.core import recipe as R
from kaika.core.simulate import _lookahead_boost
from kaika.core.score import Score, AudioInfo, Section


def test_path_traversal_prefix_run_ids(tmp_path):
    """run_id prefix (run1 vs run12) must not allow cross-run file access."""
    runs = tmp_path / "runs"
    (runs / "run1").mkdir(parents=True)
    (runs / "run12").mkdir(parents=True)
    (runs / "run12" / "secret.txt").write_text("nope")
    (runs / "run1" / "run.json").write_text(json.dumps({"id": "run1"}))
    app = create_app(runs_root=runs, data_dir=tmp_path / "data")
    with TestClient(app) as c:
        r = c.get("/api/runs/run1/files/../run12/secret.txt")
        assert r.status_code == 404


def test_lookahead_zero_no_crash():
    score = Score(audio=AudioInfo(sr=22050, duration_s=2.0, fps=24, hop_length=918),
                  tempo_bpm=120.0,
                  sections=[Section(start=0.0, end=2.0, label="drop", energy=1.0)])
    # frame exactly at the drop start with lookahead 0 used to ZeroDivision
    assert _lookahead_boost(score, frame_i=0, fps=24, lookahead_s=0.0) == 0.0


def test_recipe_null_keeps_defaults():
    r = R.from_dict({"fluid": {"vorticity": None, "dissipation": None}})
    # null in YAML must not wipe nested defaults
    assert r.fluid.vorticity.min == R.Vorticity().min
    assert r.fluid.dissipation == R.FluidConfig().dissipation


def test_lookahead_zero_in_full_sim(track_wav, tmp_path):
    from kaika.core.analyze import analyze
    from kaika.core.simulate import simulate
    score = analyze(track_wav, fps=24)
    rec = R.from_dict({"fluid": {"resolution": 40, "render_resolution": 40,
                                 "lookahead_s": 0.0}})
    res = simulate(score, rec, tmp_path, max_frames=5)
    assert res.n_frames == 5
