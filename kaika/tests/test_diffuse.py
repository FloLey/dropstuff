"""Phase 5: E4 diffusion — interface, scheduling, local fallback, comfy scaffold."""
from __future__ import annotations

import numpy as np
import imageio.v2 as imageio

from kaika.core.analyze import analyze
from kaika.core import recipe as R
from kaika.core.simulate import simulate
from kaika.core.control import generate_control
from kaika.core import diffuse as D
from kaika.core.diffuse.base import (build_prompt_schedule, compress_schedule,
                                     plan_chunks)
from kaika.core.diffuse.comfy import (build_workflow, load_workflow_template,
                                      dominant_prompt, ComfyDiffuser, ComfyUnavailable)


# ---- scheduling (model-agnostic, the durable part) -------------------------
def test_prompt_schedule_covers_every_frame(track_wav):
    score = analyze(track_wav, fps=24)
    rec = R.load_recipe("eclosion")
    sched = build_prompt_schedule(score, rec, score.n_frames)
    assert len(sched) == score.n_frames
    assert all(p.startswith(rec.prompts["base"]) for p in sched)


def test_compress_schedule_change_points():
    per_frame = ["a", "a", "b", "b", "b", "a"]
    assert compress_schedule(per_frame) == [(0, "a"), (2, "b"), (5, "a")]


def test_plan_chunks_cover_and_overlap():
    chunks = plan_chunks(100, chunk_frames=30, overlap=6)
    assert chunks[0][0] == 0
    assert chunks[-1][1] == 100
    # contiguous coverage with the requested overlap
    for (s0, e0), (s1, e1) in zip(chunks, chunks[1:]):
        assert s1 == e0 - 6
    # union covers everything
    covered = set()
    for s, e in chunks:
        covered.update(range(s, e))
    assert covered == set(range(100))


def test_plan_chunks_snaps_to_boundary():
    # a boundary near the natural cut (30) should pull the seam onto it
    chunks = plan_chunks(100, chunk_frames=30, overlap=6, boundaries=[28])
    assert chunks[0][1] == 28


# ---- comfy workflow patching ----------------------------------------------
def test_build_workflow_patches_tokens():
    tpl = load_workflow_template("wan-2.2-vace")
    wf = build_workflow(tpl, prompt="peonies", seed=99, denoise=0.5,
                        control_video="/tmp/c.mp4", output_prefix="out")
    assert wf["3"]["inputs"]["text"] == "peonies"
    assert wf["6"]["inputs"]["seed"] == 99
    assert wf["6"]["inputs"]["denoise"] == 0.5
    assert wf["1"]["inputs"]["video"] == "/tmp/c.mp4"
    # template itself is untouched (deepcopy)
    assert tpl["3"]["inputs"]["text"] == "PROMPT"


def test_dominant_prompt():
    per_frame = ["intro", "drop", "drop", "drop", "outro"]
    assert dominant_prompt(per_frame, 1, 4) == "drop"


def test_comfy_unavailable_is_clear():
    rec = R.from_dict({"diffusion": {"backend": "comfyui"}})
    d = ComfyDiffuser(endpoint="http://127.0.0.1:9", timeout=0.5)
    try:
        d._post_prompt({"x": 1})
        assert False, "expected ComfyUnavailable"
    except ComfyUnavailable as e:
        assert "not reachable" in str(e)


# ---- local fallback (runs end-to-end, no GPU) ------------------------------
def _pipeline_to_control(track_wav, tmp_path, frames=10):
    score = analyze(track_wav, fps=24)
    rec = R.from_dict({"seed": 4, "fluid": {"resolution": 48, "render_resolution": 64},
                       "diffusion": {"backend": "local", "strength": 0.6}})
    sim = simulate(score, rec, tmp_path, max_frames=frames)
    ctrl = generate_control(sim.fluid_dir, sim.velocity_dir, tmp_path)
    req = D.DiffuseRequest(fluid_dir=sim.fluid_dir, control_dirs=ctrl.dirs,
                           out_dir=tmp_path, score=score, recipe=rec, n_frames=frames)
    return rec, req


def test_get_diffuser_local():
    rec = R.from_dict({"diffusion": {"backend": "local"}})
    assert isinstance(D.get_diffuser(rec), D.LocalStylizer)


def test_local_stylizer_outputs(track_wav, tmp_path):
    rec, req = _pipeline_to_control(track_wav, tmp_path, frames=10)
    res = D.get_diffuser(rec).run(req)
    styled = sorted(res.styled_dir.glob("*.png"))
    assert len(styled) == 10 == res.n_frames
    img = imageio.imread(styled[-1])
    assert img.shape == (64, 64, 3)


def test_local_stylizer_deterministic(track_wav, tmp_path):
    rec, req = _pipeline_to_control(track_wav, tmp_path, frames=6)
    a = D.LocalStylizer().run(req).styled_dir
    # re-run into a fresh out dir
    req2 = D.DiffuseRequest(fluid_dir=req.fluid_dir, control_dirs=req.control_dirs,
                            out_dir=tmp_path / "b", score=req.score, recipe=rec,
                            n_frames=6)
    b = D.LocalStylizer().run(req2).styled_dir
    ia = imageio.imread(sorted(a.glob("*.png"))[-1])
    ib = imageio.imread(sorted(b.glob("*.png"))[-1])
    assert np.array_equal(ia, ib)
