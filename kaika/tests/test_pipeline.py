"""Phase 6: end-to-end pipeline orchestration + CLI run."""
from __future__ import annotations

from pathlib import Path

from kaika.core.analyze import analyze  # noqa
from kaika.core import recipe as R
from kaika.core.pipeline import run_pipeline, load_run, list_runs


def _fast_recipe():
    return R.from_dict({
        "name": "fast", "seed": 11,
        "fluid": {"resolution": 48, "render_resolution": 64},
        "diffusion": {"backend": "local", "control": ["depth", "flow"]},
        "post": {"fps": 24, "aspect": "square"},
    })


def test_end_to_end_local(track_wav, tmp_path):
    res = run_pipeline(track_wav, _fast_recipe(), runs_root=tmp_path, seconds=0.4)
    assert res.final.exists() and res.final.stat().st_size > 1000
    rd = res.run_dir
    # every intermediate and the frozen inputs are on disk
    assert (rd / "score.json").exists()
    assert (rd / "recipe.yaml").exists()
    assert any((rd / "fluid").glob("*.png"))
    assert any((rd / "velocity").glob("*.npy"))
    assert any((rd / "control" / "depth").glob("*.png"))
    assert any((rd / "styled").glob("*.png"))
    assert res.backend == "local"


def test_manifest_records_stages(track_wav, tmp_path):
    res = run_pipeline(track_wav, _fast_recipe(), runs_root=tmp_path, seconds=0.4)
    m = load_run(res.run_dir)
    assert m["status"] == "done"
    for stage in ("analyze", "simulate", "control", "diffuse", "post"):
        assert m["stages"][stage]["done"] is True
    assert m["sync"] is not None
    assert m["final"] == "kaika_final.mp4"


def test_progress_callback_fires(track_wav, tmp_path):
    seen = set()
    run_pipeline(track_wav, _fast_recipe(), runs_root=tmp_path, seconds=0.3,
                 progress=lambda s, d, t: seen.add(s))
    assert {"analyze", "simulate", "control", "diffuse", "post"} <= seen


def test_list_runs(track_wav, tmp_path):
    run_pipeline(track_wav, _fast_recipe(), runs_root=tmp_path, seconds=0.3)
    run_pipeline(track_wav, _fast_recipe(), runs_root=tmp_path, seconds=0.3)
    runs = list_runs(tmp_path)
    assert len(runs) == 2
    assert all("id" in r for r in runs)


def test_seconds_limits_frames(track_wav, tmp_path):
    res = run_pipeline(track_wav, _fast_recipe(), runs_root=tmp_path, seconds=0.25)
    # 0.25s * 24fps = 6 frames
    assert res.n_frames == 6


def test_cli_run(track_wav, tmp_path):
    from kaika.cli import main
    # write a tiny recipe file so --recipe path works without the package dir
    rp = tmp_path / "fast.yaml"
    _fast_recipe().to_yaml(rp)
    rc = main(["run", str(track_wav), "--recipe", str(rp),
               "--seconds", "0.3", "--out", str(tmp_path / "runs")])
    assert rc == 0
    assert list_runs(tmp_path / "runs")
