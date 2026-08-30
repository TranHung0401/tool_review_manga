"""Unit tests for FastAPI Web Dashboard endpoints."""

from pathlib import Path

from fastapi.testclient import TestClient

from manga_pipeline.web.app import create_app


def test_web_api_endpoints() -> None:
    """Test core REST endpoints of the local web dashboard."""
    app = create_app(Path("."))
    client = TestClient(app)

    # 1. Test GET /api/project
    res_proj = client.get("/api/project")
    assert res_proj.status_code == 200
    assert "schema_version" in res_proj.json()

    # 2. Test GET /api/chapters
    res_ch = client.get("/api/chapters")
    assert res_ch.status_code == 200
    assert isinstance(res_ch.json(), list)

    # 3. Test GET Dashboard HTML
    res_html = client.get("/")
    assert res_html.status_code == 200
    assert "MangaRecap Studio" in res_html.text

    # 4. Test POST /api/overrides/{anchor_id}
    res_override = client.post("/api/overrides/ta_000001", json={"text": "Dashboard override test", "reviewed": True})
    assert res_override.status_code == 200
    assert res_override.json()["status"] == "success"

    # 5. Test GET /api/grid-data/{chapter_id}
    res_grid = client.get("/api/grid-data/ch_sample")
    assert res_grid.status_code == 200
    grid_data = res_grid.json()
    assert "rows" in grid_data
    assert "total_rows" in grid_data

    # 6. Test POST /api/effects/bulk-apply
    res_fx = client.post(
        "/api/effects/bulk-apply",
        json={
            "chapter_id": "ch_sample",
            "panel_anchors": ["pa_000001"],
            "keyframe_template": "tpl_slow_zoom",
        },
    )
    assert res_fx.status_code == 200
    assert res_fx.json()["status"] == "success"
