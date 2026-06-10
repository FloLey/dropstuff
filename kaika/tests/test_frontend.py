"""Phase 8: the built frontend is embedded and served by the API server."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kaika.server.app import create_app, WEBAPP_DIST


built = (WEBAPP_DIST / "index.html").exists()


@pytest.mark.skipif(not built, reason="frontend not built (run `npm run build` in webapp/)")
def test_spa_is_served(tmp_path):
    app = create_app(runs_root=tmp_path / "runs", data_dir=tmp_path / "data")
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert '<div id="root">' in r.text
        # API still reachable alongside the static mount
        assert c.get("/api/recipes").status_code == 200


@pytest.mark.skipif(not built, reason="frontend not built")
def test_assets_present():
    assert any((WEBAPP_DIST / "assets").glob("*.js"))
    assert any((WEBAPP_DIST / "assets").glob("*.css"))
