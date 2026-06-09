"""Background job queue: one render at a time, with live progress state.

A single worker thread drains a FIFO queue (the local sim already saturates the
machine). Progress is kept in a thread-safe in-memory dict that the WebSocket
endpoint polls and streams — no cross-thread asyncio juggling.
"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

from ..core import recipe as R
from ..core.pipeline import run_pipeline
from .db import JobDB


class JobManager:
    def __init__(self, runs_root: str | Path, db: JobDB):
        self.runs_root = Path(runs_root)
        self.db = db
        self._q: "queue.Queue[str]" = queue.Queue()
        self._jobs: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        # rehydrate history from db (mark interrupted jobs as such)
        for row in db.all():
            self._jobs[row["id"]] = {
                "id": row["id"], "status": row["status"], "stage": None,
                "done": 0, "total": 0, "run_id": row["run_id"],
                "error": row["error"], "recipe": row["recipe"],
            }

    def _ensure_worker(self):
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._loop, daemon=True)
            self._worker.start()

    def submit(self, audio_path: str | Path, recipe, seconds=None,
               recipe_name: str = "") -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id, "status": "queued", "stage": None, "done": 0,
                "total": 0, "run_id": None, "error": None,
                "recipe": recipe_name or getattr(recipe, "name", "recipe"),
                "_audio": str(audio_path), "_recipe": recipe, "_seconds": seconds,
            }
        self.db.create(job_id, self._jobs[job_id]["recipe"], Path(audio_path).name)
        self._q.put(job_id)
        self._ensure_worker()
        return job_id

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            j = self._jobs.get(job_id)
            return {k: v for k, v in j.items() if not k.startswith("_")} if j else None

    def _set(self, job_id: str, **fields):
        with self._lock:
            self._jobs[job_id].update(fields)

    def _loop(self):
        while True:
            try:
                job_id = self._q.get(timeout=1.0)
            except queue.Empty:
                return  # idle -> let the thread die; resurrected on next submit
            self._run_one(job_id)

    def _run_one(self, job_id: str):
        with self._lock:
            job = self._jobs[job_id]
            audio, recipe, seconds = job["_audio"], job["_recipe"], job["_seconds"]
        self._set(job_id, status="running")
        self.db.update(job_id, status="running")

        def progress(stage, done, total):
            self._set(job_id, stage=stage, done=done, total=total)

        try:
            res = run_pipeline(audio, recipe, runs_root=self.runs_root,
                               seconds=seconds, progress=progress)
            self._set(job_id, status="done", run_id=res.run_id, stage="post",
                      done=1, total=1)
            self.db.update(job_id, status="done", run_id=res.run_id)
        except Exception as e:  # noqa
            self._set(job_id, status="error", error=f"{type(e).__name__}: {e}")
            self.db.update(job_id, status="error", error=f"{type(e).__name__}: {e}")
