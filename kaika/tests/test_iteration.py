"""Package A: fast iteration — segment preview + draft mode over the API."""
from __future__ import annotations

import pytest

from conftest import SMALL_RECIPE as SMALL, upload_audio as _upload, wait_for_job as _wait


@pytest.fixture
def client(api_client):
    return api_client


def _make_project(client, tmp_path, seconds=1.0):
    aid = _upload(client, tmp_path, duration=1.5)
    return client.post("/api/projects", json={"audio_id": aid, "recipe": SMALL,
                                              "seconds": seconds}).json()


def test_segment_preview_endpoint(client, tmp_path):
    data = _make_project(client, tmp_path)
    run_id = data["run_id"]
    job = client.post(f"/api/projects/{run_id}/preview_segment",
                      json={"index": 0, "draft": True}).json()["job_id"]
    j = _wait(client, job)
    assert j["status"] == "done", j.get("error")
    assert j["kind"] == "fluid_segment"
    r = client.get(f"/api/runs/{run_id}/files/segment_preview.mp4")
    assert r.status_code == 200
    # full fluid was never built — only the segment window
    assert not (tmp_path / "runs" / run_id / "fluid").exists()


def test_segment_preview_bad_index(client, tmp_path):
    data = _make_project(client, tmp_path)
    r = client.post(f"/api/projects/{data['run_id']}/preview_segment",
                    json={"index": 99})
    assert r.status_code == 400


def test_full_preview_draft_flag(client, tmp_path):
    data = _make_project(client, tmp_path)
    run_id = data["run_id"]
    job = client.post(f"/api/projects/{run_id}/preview",
                      json={"draft": True}).json()["job_id"]
    assert _wait(client, job)["status"] == "done"
    m = client.get(f"/api/runs/{run_id}").json()
    assert m["stages"]["simulate"]["draft"] is True
