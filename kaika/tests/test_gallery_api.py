"""Package D: cancel, live frame peek."""
from __future__ import annotations

import time

import pytest

from conftest import SMALL_RECIPE as SMALL, upload_audio as _upload, wait_for_job as _wait


@pytest.fixture
def client(api_client):
    return api_client


def _project(client, tmp_path, seconds=1.0):
    aid = _upload(client, tmp_path, duration=1.5)
    return client.post("/api/projects", json={"audio_id": aid, "recipe": SMALL,
                                              "seconds": seconds}).json()["run_id"]


def test_cancel_running_job(client, tmp_path):
    run_id = _project(client, tmp_path, seconds=1.0)
    job = client.post(f"/api/projects/{run_id}/preview", json={}).json()["job_id"]
    # cancel as soon as it is seen running (or still queued)
    deadline = time.time() + 30
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{job}").json()
        if j["status"] in ("queued", "running"):
            assert client.post(f"/api/jobs/{job}/cancel").json()["ok"]
            break
        time.sleep(0.05)
    deadline = time.time() + 60
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{job}").json()
        if j["status"] in ("cancelled", "done", "error"):
            break
        time.sleep(0.2)
    assert j["status"] == "cancelled"
    # cancelling again is a 409
    assert client.post(f"/api/jobs/{job}/cancel").status_code == 409


def test_latest_frame_during_and_after(client, tmp_path):
    run_id = _project(client, tmp_path, seconds=0.5)
    assert client.get(f"/api/runs/{run_id}/latest_frame").status_code == 404
    job = client.post(f"/api/projects/{run_id}/preview", json={}).json()["job_id"]
    assert _wait(client, job)["status"] == "done"
    r = client.get(f"/api/runs/{run_id}/latest_frame")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
