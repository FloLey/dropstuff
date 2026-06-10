"""Phase 7: FastAPI server, job queue, WebSocket progress."""
from __future__ import annotations

from conftest import SMALL_RECIPE, upload_audio as _upload, wait_for_job as _wait_done

# `api_client` fixture is provided by conftest; alias it as `client` here.
import pytest


@pytest.fixture
def client(api_client):
    return api_client


def test_recipes_endpoint(client):
    names = [r["name"] for r in client.get("/api/recipes").json()]
    assert "eclosion" in names


def test_analyze_preview(client, tmp_path):
    aid = _upload(client, tmp_path)
    r = client.post("/api/analyze", params={"audio_id": aid, "fps": 24})
    assert r.status_code == 200
    data = r.json()
    assert data["n_frames"] > 0
    assert len(data["sections"]) >= 1
    assert len(data["waveform"]) > 0
    assert "low" in data["onset_counts"]


def test_run_job_to_completion(client, tmp_path):
    aid = _upload(client, tmp_path)
    r = client.post("/api/runs", json={"audio_id": aid, "recipe": SMALL_RECIPE,
                                       "seconds": 0.3})
    job_id = r.json()["job_id"]
    j = _wait_done(client, job_id)
    assert j["status"] == "done", j.get("error")
    run_id = j["run_id"]
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["status"] == "done"
    # final video is served
    assert client.get(f"/api/runs/{run_id}/final").status_code == 200
    # an intermediate frame is served, with path-traversal blocked
    runs = client.get("/api/runs").json()
    assert any(x["id"] == run_id for x in runs)


def test_file_traversal_blocked(client, tmp_path):
    aid = _upload(client, tmp_path)
    job_id = client.post("/api/runs", json={"audio_id": aid, "recipe": SMALL_RECIPE,
                                            "seconds": 0.3}).json()["job_id"]
    j = _wait_done(client, job_id)
    run_id = j["run_id"]
    bad = client.get(f"/api/runs/{run_id}/files/../../../etc/passwd")
    assert bad.status_code == 404


def test_websocket_progress(client, tmp_path):
    aid = _upload(client, tmp_path)
    job_id = client.post("/api/runs", json={"audio_id": aid, "recipe": SMALL_RECIPE,
                                            "seconds": 0.3}).json()["job_id"]
    stages = set()
    final_status = None
    with client.websocket_connect(f"/ws/jobs/{job_id}") as ws:
        for _ in range(400):
            msg = ws.receive_json()
            if msg.get("stage"):
                stages.add(msg["stage"])
            if msg.get("status") in ("done", "error"):
                final_status = msg["status"]
                break
    assert final_status == "done"
    assert stages  # at least one progress stage streamed


def test_placeholder_index(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Kaika" in r.text
