"""Background job queue: one task at a time, with live progress state.

A single worker thread drains a FIFO queue (the local sim already saturates the
machine). A job wraps any callable ``fn(progress) -> result`` — a full render, a
fluid-only preview, or a diffuse-resume — so the same machinery serves every
stage. Progress lives in a thread-safe dict the WebSocket endpoint polls.
"""
from __future__ import annotations

import logging
import queue
import threading
import uuid
from pathlib import Path
from typing import Callable, Dict, Optional

from .db import JobDB

logger = logging.getLogger("kaika.jobs")


class JobCancelled(BaseException):
    """Raised inside a job's progress callback to stop it cooperatively.

    Inherits BaseException (like KeyboardInterrupt) so the pipeline's own
    ``except Exception`` error handling lets it pass through untouched."""


class JobManager:
    def __init__(self, runs_root: str | Path, db: JobDB):
        self.runs_root = Path(runs_root)
        self.db = db
        self._q: "queue.Queue[str]" = queue.Queue()
        self._jobs: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        for row in db.all():
            self._jobs[row["id"]] = {
                "id": row["id"], "status": row["status"], "stage": None,
                "done": 0, "total": 0, "run_id": row["run_id"],
                "error": row["error"], "kind": row["recipe"],
            }

    def _ensure_worker(self):
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._loop, daemon=True)
            self._worker.start()

    def submit(self, fn: Callable[[Callable], object], run_id: Optional[str] = None,
               kind: str = "render") -> str:
        """Queue ``fn(progress)``; ``run_id`` is the target run if known upfront."""
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id, "status": "queued", "stage": None, "done": 0,
                "total": 0, "run_id": run_id, "error": None, "kind": kind, "_fn": fn,
            }
        self.db.create(job_id, kind, run_id or "")
        self._q.put(job_id)
        self._ensure_worker()
        return job_id

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            j = self._jobs.get(job_id)
            return {k: v for k, v in j.items() if not k.startswith("_")} if j else None

    def cancel(self, job_id: str) -> bool:
        """Request cooperative cancellation; takes effect at the next progress
        tick (running) or when dequeued (queued). Returns False if unknown/finished."""
        with self._lock:
            j = self._jobs.get(job_id)
            if j is None or j["status"] in ("done", "error", "cancelled"):
                return False
            j["_cancel"] = True
            return True

    def _set(self, job_id: str, **fields):
        with self._lock:
            self._jobs[job_id].update(fields)

    def _loop(self):
        while True:
            try:
                job_id = self._q.get(timeout=1.0)
            except queue.Empty:
                return
            self._run_one(job_id)

    def _run_one(self, job_id: str):
        with self._lock:
            job = self._jobs[job_id]
            fn = job["_fn"]
            if job.get("_cancel"):
                job["status"] = "cancelled"
                self.db.update(job_id, status="cancelled")
                return
        self._set(job_id, status="running")
        self.db.update(job_id, status="running")

        def progress(stage, done, total):
            with self._lock:
                if self._jobs[job_id].get("_cancel"):
                    raise JobCancelled()
                self._jobs[job_id].update(stage=stage, done=done, total=total)

        try:
            res = fn(progress)
            run_id = getattr(res, "run_id", None) or self._jobs[job_id].get("run_id")
            self._set(job_id, status="done", run_id=run_id, done=1, total=1)
            self.db.update(job_id, status="done", run_id=run_id or "")
        except JobCancelled:
            self._set(job_id, status="cancelled")
            self.db.update(job_id, status="cancelled")
        except Exception as e:  # noqa
            logger.exception("job %s failed", job_id)
            self._set(job_id, status="error", error=f"{type(e).__name__}: {e}")
            self.db.update(job_id, status="error", error=f"{type(e).__name__}: {e}")
