"""FastAPI app: API + WebSocket progress + static frontend.

The UI and the CLI call the very same core library. Nothing the UI shows is
hidden state — runs live on disk under ``runs/`` and are served straight from
there.
"""
from __future__ import annotations

import asyncio
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
from ..core.pipeline import load_run, list_runs
from .db import JobDB
from .jobs import JobManager

WEBAPP_DIST = Path(__file__).resolve().parents[1] / "webapp_dist"


class RunRequest(BaseModel):
    audio_id: str
    recipe_name: Optional[str] = None
    recipe: Optional[dict] = None
    seconds: Optional[float] = None


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
    @app.post("/api/runs")
    def start_run(req: RunRequest):
        path = _resolve_audio(req.audio_id)
        if req.recipe is not None:
            rec = R.from_dict(req.recipe)
            name = rec.name
        else:
            rec = R.load_recipe(req.recipe_name or "eclosion")
            name = rec.name
        job_id = jm.submit(path, rec, seconds=req.seconds, recipe_name=name)
        return {"job_id": job_id}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        j = jm.get(job_id)
        if not j:
            raise HTTPException(404, "job not found")
        return j

    @app.get("/api/jobs")
    def jobs():
        return db.all()

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
