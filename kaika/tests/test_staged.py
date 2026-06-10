"""Phase S2: staged pipeline (fluid preview first, diffuse resumes)."""
from __future__ import annotations

from kaika.core.analyze import analyze
from kaika.core import recipe as R
from kaika.core.project import Project
from kaika.core.pipeline import run_fluid, run_diffuse, load_run


def _project(track_wav, seconds=0.4):
    score = analyze(track_wav, fps=24)
    rec = R.from_dict({"seed": 2, "fluid": {"resolution": 48, "render_resolution": 48},
                       "diffusion": {"backend": "local", "control": ["depth"]}})
    proj = Project.from_score(score, rec, audio=track_wav.name)
    proj.seconds = seconds
    return proj, score


def test_fluid_stage_produces_preview_no_diffusion(track_wav, tmp_path):
    proj, score = _project(track_wav)
    res = run_fluid(proj, track_wav, runs_root=tmp_path, score=score)
    rd = res.run_dir
    assert (rd / "fluid_preview.mp4").exists()
    assert (rd / "project.json").exists()
    assert (rd / "score.json").exists()
    assert any((rd / "fluid").glob("*.png"))
    assert any((rd / "control" / "depth").glob("*.png"))
    assert not (rd / "styled").exists()        # diffusion not run yet
    assert load_run(rd)["stage"] == "fluid"
    assert res.backend == "fluid"


def test_diffuse_resumes_fluid_run(track_wav, tmp_path):
    proj, score = _project(track_wav)
    fluid = run_fluid(proj, track_wav, runs_root=tmp_path, score=score)
    res = run_diffuse(fluid.run_dir)
    rd = res.run_dir
    assert any((rd / "styled").glob("*.png"))
    assert (rd / "kaika_final.mp4").exists()
    m = load_run(rd)
    assert m["stage"] == "done" and m["status"] == "done"
    assert m["stages"]["diffuse"]["done"] is True
    assert res.backend == "local"


def test_repreview_overwrites_same_run(track_wav, tmp_path):
    """Editing params and re-previewing into the same run id refreshes the fluid."""
    proj, score = _project(track_wav)
    r1 = run_fluid(proj, track_wav, runs_root=tmp_path, run_id="myrun", score=score)
    # change a segment param and re-run into the same id
    proj.segments[-1].fluid = {"vorticity": {"min": 4, "max": 70}}
    r2 = run_fluid(proj, track_wav, runs_root=tmp_path, run_id="myrun", score=score)
    assert r1.run_dir == r2.run_dir
    saved = Project.from_json(r2.run_dir / "project.json")
    assert saved.segments[-1].fluid["vorticity"]["max"] == 70
