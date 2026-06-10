"""FastAPI app: API + WebSocket progress + static frontend.

The UI and the CLI call the very same core library. Nothing the UI shows is
hidden state — runs live on disk under ``runs/`` and are served straight from
there.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..core import recipe as R
from ..core.analyze import analyze
from ..core.project import Project
from ..core.score import Score
from ..core.pipeline import (load_run, list_runs, run_pipeline, run_fluid,
                             run_diffuse, run_segment_preview, init_project_run,
                             frozen_audio)
from .db import JobDB
from .jobs import JobManager

WEBAPP_DIST = Path(__file__).resolve().parents[1] / "webapp_dist"


class RunRequest(BaseModel):
    audio_id: str
    recipe_name: Optional[str] = None
    recipe: Optional[dict] = None
    seconds: Optional[float] = None


class ProjectRequest(BaseModel):
    audio_id: str
    recipe_name: Optional[str] = None
    recipe: Optional[dict] = None
    seconds: Optional[float] = None


class ProjectUpdate(BaseModel):
    segments: Optional[list] = None
    recipe: Optional[dict] = None
    seconds: Optional[float] = None


class PreviewRequest(BaseModel):
    draft: bool = False


class SegmentPreviewRequest(BaseModel):
    index: int
    draft: bool = True


def _waveform_peaks(y: np.ndarray, buckets: int = 800) -> list:
    if len(y) == 0:
        return []
    n = min(buckets, len(y))
    edges = np.linspace(0, len(y), n + 1).astype(int)
    return [round(float(np.abs(y[a:b]).max()) if b > a else 0.0, 4)
            for a, b in zip(edges[:-1], edges[1:])]


def create_app(runs_root: str | Path = "runs",
               data_dir: str | Path | None = None) -> FastAPI:
    runs_root = Path(runs_root)
    data_dir = Path(data_dir) if data_dir else runs_root.parent / ".kaika"
    uploads = data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    runs_root.mkdir(parents=True, exist_ok=True)

    db = JobDB(data_dir / "kaika.db")
    jm = JobManager(runs_root, db)

    app = FastAPI(title="Kaika")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])
    app.state.jm = jm
    app.state.runs_root = runs_root
    app.state.uploads = uploads

    # ---- recipes ----------------------------------------------------------
    @app.get("/api/recipes")
    def recipes():
        out = []
        for p in sorted(R.RECIPES_DIR.glob("*.yaml")):
            try:
                out.append({"name": p.stem, "yaml": p.read_text(),
                            "recipe": R.load_recipe(p).to_dict()})
            except Exception:  # noqa
                pass
        return out

    # ---- upload + analyze (Studio) ----------------------------------------
    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)):
        suffix = Path(file.filename or "audio.wav").suffix or ".wav"
        audio_id = uuid.uuid4().hex[:12]
        dest = uploads / f"{audio_id}{suffix}"
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        return {"audio_id": audio_id, "name": file.filename}

    def _resolve_audio(audio_id: str) -> Path:
        hits = list(uploads.glob(f"{audio_id}.*"))
        if not hits:
            raise HTTPException(404, f"audio {audio_id} not found")
        return hits[0]

    @app.post("/api/analyze")
    def analyze_audio(audio_id: str, fps: int = 24):
        import librosa
        path = _resolve_audio(audio_id)
        score = analyze(path, fps=fps)
        y, sr = librosa.load(str(path), sr=None, mono=True)
        return {
            "audio_id": audio_id, "tempo_bpm": score.tempo_bpm,
            "duration_s": score.audio.duration_s, "fps": fps,
            "n_frames": score.n_frames,
            "sections": [s.__dict__ for s in score.sections],
            "beats": [b.__dict__ for b in score.beats],
            "onset_counts": {k: len(v) for k, v in score.onsets.items()},
            "waveform": _waveform_peaks(y),
        }

    # ---- runs (jobs) ------------------------------------------------------
    def _recipe_from(req) -> R.Recipe:
        if req.recipe is not None:
            return R.from_dict(req.recipe)
        return R.load_recipe(req.recipe_name or "eclosion")

    @app.post("/api/runs")
    def start_run(req: RunRequest):
        path = _resolve_audio(req.audio_id)
        rec = _recipe_from(req)
        job_id = jm.submit(
            lambda progress: run_pipeline(path, rec, runs_root=runs_root,
                                          seconds=req.seconds, progress=progress),
            kind="render")
        return {"job_id": job_id}

    # ---- projects (segment editor) ----------------------------------------
    def _analysis_payload(rd: Path) -> Optional[dict]:
        """Persistent analysis view for the editor: score data + cached waveform."""
        score_path = rd / "score.json"
        if not score_path.exists():
            return None
        score = Score.from_json(score_path)
        wf_path = rd / "waveform.json"
        if wf_path.exists():
            waveform = json.loads(wf_path.read_text())
        else:
            import librosa
            audio = frozen_audio(rd)
            if audio is None:
                waveform = []
            else:
                y, _sr = librosa.load(str(audio), sr=None, mono=True)
                waveform = _waveform_peaks(y)
            wf_path.write_text(json.dumps(waveform))
        return {
            "tempo_bpm": score.tempo_bpm, "duration_s": score.audio.duration_s,
            "fps": score.audio.fps, "n_frames": score.n_frames,
            "beats": [b.__dict__ for b in score.beats],
            "onsets": {k: [round(e.t, 3) for e in v] for k, v in score.onsets.items()},
            "onset_counts": {k: len(v) for k, v in score.onsets.items()},
            "waveform": waveform,
        }

    def _project_payload(run_id: str, with_analysis: bool = False) -> dict:
        rd = runs_root / run_id
        if not (rd / "project.json").exists():
            raise HTTPException(404, "project not found")
        audio = frozen_audio(rd)
        payload = {
            "run_id": run_id,
            "project": Project.from_json(rd / "project.json").to_dict(),
            "manifest": load_run(rd),
            "audio_url": f"/api/runs/{run_id}/files/{audio.name}" if audio else None,
        }
        if with_analysis:
            payload["analysis"] = _analysis_payload(rd)
        return payload

    @app.post("/api/projects")
    def create_project(req: ProjectRequest):
        path = _resolve_audio(req.audio_id)
        rec = _recipe_from(req)
        run_dir, project, score = init_project_run(path, rec, runs_root=runs_root,
                                                   seconds=req.seconds)
        return _project_payload(run_dir.name, with_analysis=True)

    @app.get("/api/projects/{run_id}")
    def get_project(run_id: str):
        return _project_payload(run_id, with_analysis=True)

    @app.put("/api/projects/{run_id}")
    def update_project(run_id: str, upd: ProjectUpdate):
        rd = runs_root / run_id
        if not (rd / "project.json").exists():
            raise HTTPException(404, "project not found")
        proj = Project.from_json(rd / "project.json")
        if upd.recipe is not None:
            proj.recipe = R.from_dict(upd.recipe)
        if upd.seconds is not None:
            proj.seconds = upd.seconds
        if upd.segments is not None:
            from ..core.project import Segment
            proj.segments = [Segment(**s) for s in upd.segments]
        proj.to_json(rd / "project.json")
        return _project_payload(run_id)

    @app.post("/api/projects/{run_id}/preview")
    def preview_project(run_id: str, req: PreviewRequest = PreviewRequest()):
        rd = runs_root / run_id
        if not (rd / "project.json").exists():
            raise HTTPException(404, "project not found")

        def task(progress):
            proj = Project.from_json(rd / "project.json")
            score = Score.from_json(rd / "score.json")
            audio = frozen_audio(rd)
            if audio is None:
                raise FileNotFoundError("frozen audio missing for project")
            return run_fluid(proj, audio, runs_root=runs_root, run_id=run_id,
                             score=score, draft=req.draft, progress=progress)

        return {"job_id": jm.submit(task, run_id=run_id, kind="fluid")}

    @app.post("/api/projects/{run_id}/preview_segment")
    def preview_segment(run_id: str, req: SegmentPreviewRequest):
        rd = runs_root / run_id
        if not (rd / "project.json").exists():
            raise HTTPException(404, "project not found")
        n_segs = len(Project.from_json(rd / "project.json").segments)
        if not (0 <= req.index < n_segs):
            raise HTTPException(400, f"segment index {req.index} out of range")
        return {"job_id": jm.submit(
            lambda progress: run_segment_preview(rd, req.index, draft=req.draft,
                                                 progress=progress),
            run_id=run_id, kind="fluid_segment")}

    @app.post("/api/projects/{run_id}/generate")
    def generate_project(run_id: str):
        rd = runs_root / run_id
        if not (rd / "project.json").exists():
            raise HTTPException(404, "project not found")
        # run_diffuse rebuilds missing/draft fluid itself, so this always works.
        return {"job_id": jm.submit(lambda progress: run_diffuse(rd, progress=progress),
                                    run_id=run_id, kind="diffuse")}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        j = jm.get(job_id)
        if not j:
            raise HTTPException(404, "job not found")
        return j

    @app.get("/api/jobs")
    def jobs():
        return db.all()

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        if not jm.cancel(job_id):
            raise HTTPException(409, "job not cancellable (unknown or finished)")
        return {"ok": True}

    @app.get("/api/runs/{run_id}/latest_frame")
    def latest_frame(run_id: str):
        """Most recent frame on disk for this run — live peek while rendering."""
        rd = runs_root / run_id
        candidates = []
        for sub in ("styled", "fluid", "seg_preview/fluid"):
            d = rd / sub
            if d.is_dir():
                pngs = list(d.glob("*.png"))
                if pngs:
                    candidates.append(max(pngs, key=lambda p: p.stat().st_mtime))
        if not candidates:
            raise HTTPException(404, "no frames yet")
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        return FileResponse(newest, media_type="image/png",
                            headers={"Cache-Control": "no-store"})

    @app.websocket("/ws/jobs/{job_id}")
    async def ws_job(ws: WebSocket, job_id: str):
        await ws.accept()
        last = None
        try:
            while True:
                j = jm.get(job_id)
                if j is None:
                    await ws.send_json({"error": "job not found"})
                    break
                snapshot = (j["status"], j["stage"], j["done"], j["total"])
                if snapshot != last:
                    await ws.send_json(j)
                    last = snapshot
                if j["status"] in ("done", "error"):
                    break
                await asyncio.sleep(0.15)
        except WebSocketDisconnect:
            return

    @app.get("/api/runs")
    def runs():
        return list_runs(runs_root)

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str):
        rd = runs_root / run_id
        if not (rd / "run.json").exists():
            raise HTTPException(404, "run not found")
        return load_run(rd)

    @app.get("/api/runs/{run_id}/final")
    def run_final(run_id: str):
        m = run_detail(run_id)
        final = runs_root / run_id / (m.get("final") or "kaika_final.mp4")
        if not final.exists():
            raise HTTPException(404, "final not rendered")
        return FileResponse(final, media_type="video/mp4")

    @app.get("/api/runs/{run_id}/files/{subpath:path}")
    def run_file(run_id: str, subpath: str):
        rd = (runs_root / run_id).resolve()
        target = (rd / subpath).resolve()
        try:
            target.relative_to(rd)          # strict subpath, prefix-safe
        except ValueError:
            raise HTTPException(404, "file not found")
        if not target.is_file():
            raise HTTPException(404, "file not found")
        return FileResponse(target)

    # ---- static frontend --------------------------------------------------
    if (WEBAPP_DIST / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(WEBAPP_DIST), html=True), name="web")
    else:
        @app.get("/")
        def placeholder():
            return HTMLResponse(
                "<h1>Kaika</h1><p>Frontend not built. Run "
                "<code>npm --prefix webapp install &amp;&amp; npm --prefix webapp run build</code>"
                ", then restart. API is live under <code>/api</code>.</p>")

    return app


def serve(host: str = "127.0.0.1", port: int = 8400, runs_root="runs",
          open_browser: bool = True) -> None:
    import uvicorn
    app = create_app(runs_root)
    if open_browser:
        import threading, webbrowser, time
        threading.Thread(
            target=lambda: (time.sleep(1.0), webbrowser.open(f"http://{host}:{port}")),
            daemon=True).start()
    uvicorn.run(app, host=host, port=port, log_level="info")
