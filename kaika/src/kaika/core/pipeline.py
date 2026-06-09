"""Pipeline orchestration: audio + recipe -> a reproducible run directory.

Everything is a *run*. Each invocation writes ``runs/<id>/`` with the frozen
recipe, the score, every intermediate (fluid/, velocity/, control/, styled/)
and the final clip, plus a ``run.json`` manifest. Nothing the UI shows is not
re-generable from that directory.
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, List, Optional

from .recipe import Recipe, load_recipe
from .score import Score
from .analyze import analyze
from .simulate import simulate
from .control import generate_control
from . import diffuse as D
from .post import assemble

# progress(stage, done, total)
ProgressFn = Callable[[str, int, int], None]
STAGES = ["analyze", "simulate", "control", "diffuse", "post"]


@dataclass
class RunResult:
    run_id: str
    run_dir: Path
    final: Path
    n_frames: int
    sync_lag: int
    sync_corr: float
    backend: str


def _emit(progress: Optional[ProgressFn], stage: str, done: int, total: int):
    if progress:
        progress(stage, done, total)


def run_pipeline(audio_path: str | Path, recipe: Recipe | str,
                 runs_root: str | Path = "runs", run_id: Optional[str] = None,
                 seconds: Optional[float] = None,
                 progress: Optional[ProgressFn] = None) -> RunResult:
    if isinstance(recipe, str):
        recipe = load_recipe(recipe)
    audio_path = Path(audio_path)
    run_id = run_id or f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    run_dir = Path(runs_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Freeze inputs so the run is replayable.
    recipe.to_yaml(run_dir / "recipe.yaml")
    try:
        shutil.copy2(audio_path, run_dir / ("audio" + audio_path.suffix))
        frozen_audio = run_dir / ("audio" + audio_path.suffix)
    except OSError:
        frozen_audio = audio_path

    manifest = {
        "id": run_id, "created": time.time(), "audio": audio_path.name,
        "recipe": recipe.name, "fps": recipe.post.fps, "seconds": seconds,
        "status": "running", "stages": {}, "error": None,
    }
    (run_dir / "run.json").write_text(json.dumps(manifest, indent=2))

    def save_manifest():
        (run_dir / "run.json").write_text(json.dumps(manifest, indent=2))

    try:
        fps = recipe.post.fps
        # E1
        _emit(progress, "analyze", 0, 1)
        score = analyze(frozen_audio, fps=fps)
        score.to_json(run_dir / "score.json")
        manifest["stages"]["analyze"] = {"done": True, "n_frames": score.n_frames}
        max_frames = int(round(seconds * fps)) if seconds else None
        n = min(score.n_frames, max_frames) if max_frames else score.n_frames
        manifest["n_frames"] = n
        _emit(progress, "analyze", 1, 1)

        # E2
        sim = simulate(score, recipe, run_dir, max_frames=max_frames,
                       progress=lambda d, t: _emit(progress, "simulate", d, t))
        manifest["stages"]["simulate"] = {"done": True, "n_frames": sim.n_frames}
        save_manifest()

        # E3
        signals = recipe.diffusion.control or ["depth", "flow"]
        ctrl = generate_control(
            sim.fluid_dir, sim.velocity_dir, run_dir, signals=signals,
            render_resolution=recipe.fluid.render_resolution,
            progress=lambda d, t: _emit(progress, "control", d, t))
        manifest["stages"]["control"] = {"done": True, "signals": list(ctrl.dirs)}
        save_manifest()

        # E4
        diffuser = D.get_diffuser(recipe)
        req = D.DiffuseRequest(fluid_dir=sim.fluid_dir, control_dirs=ctrl.dirs,
                               out_dir=run_dir, score=score, recipe=recipe, n_frames=n)
        dres = diffuser.run(req, progress=lambda d, t: _emit(progress, "diffuse", d, t))
        manifest["stages"]["diffuse"] = {"done": True, "backend": dres.backend,
                                         "n_frames": dres.n_frames}
        save_manifest()

        # E5 — prefer styled frames; fall back to raw fluid if backend produced none.
        styled = dres.styled_dir
        frames_for_post = styled if any(styled.glob("*.png")) else sim.fluid_dir
        _emit(progress, "post", 0, 1)
        final = run_dir / "kaika_final.mp4"
        post = assemble(frames_for_post, frozen_audio, final, fps=fps,
                        aspect=recipe.post.aspect, interpolate=recipe.post.interpolate,
                        upscale=recipe.post.upscale, score=score,
                        fluid_stats_path=sim.stats_path)
        manifest["stages"]["post"] = {"done": True}
        manifest["sync"] = asdict(post.sync) if post.sync else None
        manifest["final"] = final.name
        manifest["status"] = "done"
        _emit(progress, "post", 1, 1)
        save_manifest()

        return RunResult(
            run_id=run_id, run_dir=run_dir, final=final, n_frames=n,
            sync_lag=post.sync.lag_frames if post.sync else 0,
            sync_corr=post.sync.correlation if post.sync else 0.0,
            backend=dres.backend)
    except Exception as e:
        manifest["status"] = "error"
        manifest["error"] = f"{type(e).__name__}: {e}"
        save_manifest()
        raise


def load_run(run_dir: str | Path) -> dict:
    return json.loads((Path(run_dir) / "run.json").read_text())


def list_runs(runs_root: str | Path) -> List[dict]:
    root = Path(runs_root)
    if not root.exists():
        return []
    runs = []
    for d in sorted(root.iterdir(), reverse=True):
        m = d / "run.json"
        if m.exists():
            try:
                runs.append(json.loads(m.read_text()))
            except json.JSONDecodeError:
                pass
    return runs
