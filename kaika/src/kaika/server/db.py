"""Tiny SQLite store for the job queue/history.

Runs themselves live on disk (``runs/<id>/run.json`` is the source of truth);
this table just tracks job lifecycle so history survives a restart.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id        TEXT PRIMARY KEY,
    run_id    TEXT,
    status    TEXT NOT NULL,
    recipe    TEXT,
    audio     TEXT,
    created   REAL NOT NULL,
    error     TEXT
);
"""


class JobDB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def create(self, job_id: str, recipe: str, audio: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO jobs(id, status, recipe, audio, created) "
                "VALUES (?,?,?,?,?)",
                (job_id, "queued", recipe, audio, time.time()))
            self._conn.commit()

    def update(self, job_id: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn.execute(f"UPDATE jobs SET {cols} WHERE id=?",
                               (*fields.values(), job_id))
            self._conn.commit()

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id=?",
                                     (job_id,)).fetchone()
        return dict(row) if row else None

    def all(self) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY created DESC").fetchall()
        return [dict(r) for r in rows]
