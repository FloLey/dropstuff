"""Pipeline orchestration: a Project -> a reproducible run directory.

Two stages the editor can drive independently:
  * fluid  — E1 analyze + E2 simulate (per-segment params) + E3 control, plus a
             previewable fluid MP4. Fast, no GPU; iterate here.
  * diffuse — E4 + E5, *resuming* a run's cached fluid/control with the project's
             per-segment prompts.
``run_pipeline`` runs both for a recipe (segments default to detected sections).
Everything lands under ``runs/<id>/`` with frozen recipe, project, score, every
intermediate and a manifest — nothing the UI shows is un-reproducible.
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
from .project import Project
from .analyze import analyze
from .simulate import simulate
from .control import generate_control
from . import diffuse as D
from .post import assemble

# progress(stage, done, total)
ProgressFn = Callable[[str, int, int], None]
STAGES = ["analyze", "simulate", "control", "diffuse", "post"]
CONTROL_SIGNALS = ["depth", "canny", "flow"]


@dataclass
class RunResult:
    run_id: str
    run_dir: Path
    final: Path                  # fluid preview (fluid stage) or final clip (diffuse)
    n_frames: int
    sync_lag: int
    sync_corr: float
    backend: str


def _emit(progress: Optional[ProgressFn], stage: str, done: int, total: int):
    if progress:
        progress(stage, done, total)


def _new_run_id() -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _freeze_audio(audio_path: Path, run_dir: Path) -> Path:
    try:
        dest = run_dir / ("audio" + audio_path.suffix)
        shutil.copy2(audio_path, dest)
        return dest
    except OSError:
        return audio_path


def _frozen_audio(run_dir: Path) -> Optional[Path]:
    hits = sorted(run_dir.glob("audio.*"))
    return hits[0] if hits else None


def _load_manifest(run_dir: Path) -> dict:
    p = run_dir / "run.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _save_manifest(run_dir: Path, manifest: dict) -> None:
    (run_dir / "run.json").write_text(json.dumps(manifest, indent=2))


# ---------------------------------------------------------------------------
def init_project_run(audio_path: str | Path, recipe: Recipe, runs_root: str | Path = "runs",
                     run_id: Optional[str] = None, seconds: Optional[float] = None):
    """Create a working run dir: freeze audio + recipe, analyze, seed a Project
    from the detected sections. Does NOT simulate. Returns (run_dir, project, score)."""
    audio_path = Path(audio_path)
    run_id = run_id or _new_run_id()
    run_dir = Path(runs_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    recipe.to_yaml(run_dir / "recipe.yaml")
    frozen = _freeze_audio(audio_path, run_dir)
    score = analyze(frozen, fps=recipe.post.fps)
    score.to_json(run_dir / "score.json")
    project = Project.from_score(score, recipe, audio=frozen.name)
    project.seconds = seconds
    project.to_json(run_dir / "project.json")
    _save_manifest(run_dir, {
        "id": run_id, "created": time.time(), "audio": audio_path.name,
        "recipe": recipe.name, "fps": project.fps, "seconds": seconds,
        "stages": {}, "stage": "created", "status": "created", "error": None,
    })
    return run_dir, project, score


def run_fluid(project: Project, audio_path: str | Path, runs_root: str | Path = "runs",
              run_id: Optional[str] = None, score: Optional[Score] = None,
              progress: Optional[ProgressFn] = None) -> RunResult:
    """E1+E2+E3 + a previewable fluid clip (no diffusion)."""
    audio_path = Path(audio_path)
    run_id = run_id or _new_run_id()
    run_dir = Path(runs_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    recipe = project.recipe

    recipe.to_yaml(run_dir / "recipe.yaml")
    frozen = _freeze_audio(audio_path, run_dir)
    project.to_json(run_dir / "project.json")

    manifest = _load_manifest(run_dir) or {
        "id": run_id, "created": time.time(), "audio": audio_path.name,
        "recipe": recipe.name, "fps": project.fps, "seconds": project.seconds,
        "stages": {}, "error": None,
    }
    manifest["stage"] = "fluid_running"
    _save_manifest(run_dir, manifest)

    try:
        fps = project.fps
        _emit(progress, "analyze", 0, 1)
        if score is None:
            score = analyze(frozen, fps=fps)
        score.to_json(run_dir / "score.json")
        max_frames = int(round(project.seconds * fps)) if project.seconds else None
        n = min(score.n_frames, max_frames) if max_frames else score.n_frames
        manifest["stages"]["analyze"] = {"done": True}
        manifest["n_frames"] = n
        _emit(progress, "analyze", 1, 1)

        cfgs = project.frame_configs(n)
        sim = simulate(score, recipe, run_dir, max_frames=max_frames,
                       frame_configs=cfgs,
                       progress=lambda d, t: _emit(progress, "simulate", d, t))
        manifest["stages"]["simulate"] = {"done": True, "n_frames": sim.n_frames}

        signals = recipe.diffusion.control or ["depth", "flow"]
        ctrl = generate_control(
            sim.fluid_dir, sim.velocity_dir, run_dir, signals=signals,
            render_resolution=recipe.fluid.render_resolution,
            progress=lambda d, t: _emit(progress, "control", d, t))
        manifest["stages"]["control"] = {"done": True, "signals": list(ctrl.dirs)}

        _emit(progress, "post", 0, 1)
        preview = run_dir / "fluid_preview.mp4"
        post = assemble(sim.fluid_dir, frozen, preview, fps=fps,
                        aspect=recipe.post.aspect, score=score,
                        fluid_stats_path=sim.stats_path)
        manifest["fluid_preview"] = preview.name
        manifest["sync"] = asdict(post.sync) if post.sync else None
        manifest["stage"] = "fluid"
        manifest["status"] = "fluid"
        _emit(progress, "post", 1, 1)
        _save_manifest(run_dir, manifest)

        return RunResult(run_id=run_id, run_dir=run_dir, final=preview, n_frames=n,
                         sync_lag=post.sync.lag_frames if post.sync else 0,
                         sync_corr=post.sync.correlation if post.sync else 0.0,
                         backend="fluid")
    except Exception as e:
        manifest["stage"] = "error"
        manifest["status"] = "error"
        manifest["error"] = f"{type(e).__name__}: {e}"
        _save_manifest(run_dir, manifest)
        raise


def run_diffuse(run_dir: str | Path,
                progress: Optional[ProgressFn] = None) -> RunResult:
    """E4+E5 resuming a fluid run, using the project's per-segment prompts."""
    run_dir = Path(run_dir)
    project = Project.from_json(run_dir / "project.json")
    score = Score.from_json(run_dir / "score.json")
    recipe = project.recipe
    manifest = _load_manifest(run_dir)
    manifest["stage"] = "diffuse_running"
    _save_manifest(run_dir, manifest)

    try:
        fluid_dir = run_dir / "fluid"
        n = len(list(fluid_dir.glob("*.png")))
        control_dirs = {s: run_dir / "control" / s for s in CONTROL_SIGNALS
                        if (run_dir / "control" / s).exists()}
        diffuser = D.get_diffuser(recipe)
        req = D.DiffuseRequest(fluid_dir=fluid_dir, control_dirs=control_dirs,
                               out_dir=run_dir, score=score, recipe=recipe, n_frames=n,
                               prompts=project.prompt_schedule(n))
        dres = diffuser.run(req, progress=lambda d, t: _emit(progress, "diffuse", d, t))
        manifest["stages"]["diffuse"] = {"done": True, "backend": dres.backend}

        styled = dres.styled_dir
        frames = styled if any(styled.glob("*.png")) else fluid_dir
        frozen = _frozen_audio(run_dir) or (run_dir / "missing.wav")
        _emit(progress, "post", 0, 1)
        final = run_dir / "kaika_final.mp4"
        stats = run_dir / "fluid_stats.json"
        post = assemble(frames, frozen, final, fps=project.fps,
                        aspect=recipe.post.aspect, interpolate=recipe.post.interpolate,
                        upscale=recipe.post.upscale, score=score,
                        fluid_stats_path=stats if stats.exists() else None)
        manifest["stages"]["post"] = {"done": True}
        manifest["final"] = final.name
        manifest["sync"] = asdict(post.sync) if post.sync else manifest.get("sync")
        manifest["stage"] = "done"
        manifest["status"] = "done"
        _emit(progress, "post", 1, 1)
        _save_manifest(run_dir, manifest)

        return RunResult(run_id=manifest.get("id", run_dir.name), run_dir=run_dir,
                         final=final, n_frames=n,
                         sync_lag=post.sync.lag_frames if post.sync else 0,
                         sync_corr=post.sync.correlation if post.sync else 0.0,
                         backend=dres.backend)
    except Exception as e:
        manifest["stage"] = "error"
        manifest["status"] = "error"
        manifest["error"] = f"{type(e).__name__}: {e}"
        _save_manifest(run_dir, manifest)
        raise


def run_pipeline(audio_path: str | Path, recipe: Recipe | str,
                 runs_root: str | Path = "runs", run_id: Optional[str] = None,
                 seconds: Optional[float] = None,
                 progress: Optional[ProgressFn] = None) -> RunResult:
    """Full render for a recipe: segments default to the detected sections."""
    if isinstance(recipe, str):
        recipe = load_recipe(recipe)
    audio_path = Path(audio_path)
    score = analyze(audio_path, fps=recipe.post.fps)
    project = Project.from_score(score, recipe, audio=audio_path.name)
    project.seconds = seconds
    fluid = run_fluid(project, audio_path, runs_root=runs_root, run_id=run_id,
                      score=score, progress=progress)
    return run_diffuse(fluid.run_dir, progress=progress)


def load_run(run_dir: str | Path) -> dict:
    return _load_manifest(Path(run_dir))


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
