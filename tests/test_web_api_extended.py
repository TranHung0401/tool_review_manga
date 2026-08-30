"""Tests for the new web API endpoints: Layout Editor, reconcile, resync, CapCut."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from manga_pipeline.web.app import create_app


def _write_layout(p_dir: Path, chapter_id: str = "ch01") -> None:
    artifacts = p_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    layout = {
        "schema_version": 1,
        "stage": "layout",
        "chapter_id": chapter_id,
        "artifact_version": 1,
        "manifest": {
            "engine": "test",
            "engine_version": "1.0",
            "timestamp": "2026-08-30T10:00:00Z",
            "inputs": [],
        },
        "panels": [
            {
                "id": "p_aaa111222333",
                "source": {"image": "pages/001.png", "bbox": [0, 0, 100, 100]},
                "reading_order": 1,
                "text_regions": [],
            },
            {
                "id": "p_bbb444555666",
                "source": {"image": "pages/001.png", "bbox": [0, 120, 100, 100]},
                "reading_order": 2,
                "text_regions": [],
            },
        ],
    }
    (artifacts / f"layout.{chapter_id}.v1.json").write_text(json.dumps(layout), encoding="utf-8")


def _write_tts(p_dir: Path, version: int, duration: int, chapter_id: str = "ch01") -> None:
    artifacts = p_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    tts = {
        "schema_version": 1,
        "stage": "tts",
        "chapter_id": chapter_id,
        "artifact_version": version,
        "depends_on": {"stage": "script", "artifact_version": 1},
        "manifest": {
            "provider": "edge-tts",
            "voice_ref": "vi-VN-HoaiMyNeural",
            "timestamp": "2026-08-30T10:00:00Z",
        },
        "clips": [
            {
                "unit_id": "s_unit00000001",
                "file": f"audio/{chapter_id}_s_unit00000001.v{version}.wav",
                "duration_ms": duration,
            }
        ],
    }
    (artifacts / f"tts.{chapter_id}.v{version}.json").write_text(json.dumps(tts), encoding="utf-8")


def test_layout_editor_endpoints(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    _write_layout(tmp_path)

    # Seed anchors by requesting resolved layout first (identity)
    res = client.get("/api/layout/resolved/ch01")
    assert res.status_code == 200
    assert len(res.json()["panels"]) == 2

    # Register anchors via project state (draw creates its own anchor)
    res = client.post(
        "/api/layout/draw-panel",
        json={"chapter_id": "ch01", "image": "pages/002.png", "bbox": [0, 0, 900, 1300], "reading_order": 3},
    )
    assert res.status_code == 200
    drawn_anchor = res.json()["anchor"]
    assert drawn_anchor.startswith("pa_")

    # Delete requires pa_ anchors — invalid rejected
    res = client.post(
        "/api/layout/delete-panels", json={"chapter_id": "ch01", "panel_anchors": ["p_raw_ai_id"]}
    )
    assert res.status_code == 400

    # Valid delete
    res = client.post(
        "/api/layout/delete-panels", json={"chapter_id": "ch01", "panel_anchors": [drawn_anchor]}
    )
    assert res.status_code == 200
    assert drawn_anchor in res.json()["deleted_panels"]

    # Reading order override
    res = client.post(
        "/api/layout/reading-order", json={"chapter_id": "ch01", "orders": {drawn_anchor: 9}}
    )
    assert res.status_code == 200


def test_resync_diff_and_apply(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    _write_tts(tmp_path, 1, 3000)
    _write_tts(tmp_path, 2, 4500)

    # Build initial timeline from v1 via reconcile-free direct project edit:
    # use resync apply with v1 to bootstrap (empty timeline -> no changes) —
    # so first build the sequence through the sync policy endpoint path:
    from manga_pipeline.core.schemas.artifact_tts import TtsArtifact
    from manga_pipeline.core.schemas.project_schema import ProjectSchema, StoryMetadata
    from manga_pipeline.pipeline.sync import apply_sync_policy

    proj = ProjectSchema(story=StoryMetadata(title="T", chapters=["ch01"]))
    t1 = TtsArtifact.model_validate_json(
        (tmp_path / "artifacts" / "tts.ch01.v1.json").read_text(encoding="utf-8")
    )
    apply_sync_policy(proj, "ch01", t1)
    (tmp_path / "project.json").write_text(proj.model_dump_json(indent=2), encoding="utf-8")

    # Diff against v2 shows the 1500ms delta without mutating anything
    res = client.get("/api/resync/ch01/diff", params={"version": 2})
    assert res.status_code == 200
    diff = res.json()
    assert diff["has_changes"] is True
    assert diff["entries"][0]["delta_ms"] == 1500

    # Timeline still on v1 snapshot
    proj_now = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    assert proj_now["sequence"]["audio_tracks"][0]["clips"][0]["synced_duration_ms"] == 3000

    # Apply
    res = client.post("/api/resync/apply", json={"chapter_id": "ch01", "version": 2})
    assert res.status_code == 200
    proj_after = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    clip = proj_after["sequence"]["audio_tracks"][0]["clips"][0]
    assert clip["synced_duration_ms"] == 4500
    assert clip["synced_artifact_version"] == 2
    assert proj_after["active_artifacts"]["ch01"]["tts"] == 2


def test_export_capcut_endpoint(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    _write_layout(tmp_path)
    _write_tts(tmp_path, 1, 3000)

    res = client.post("/api/export-capcut/ch01")
    assert res.status_code == 200
    report = res.json()
    assert report["status"] in ("success", "success_with_warnings")
    bundle = Path(report["bundle_dir"])
    assert (bundle / "draft_content.json").exists()
    assert (bundle / "export_report.json").exists()


def test_orphaned_and_remap_endpoints(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    _write_layout(tmp_path)

    from manga_pipeline.core.schemas.project_schema import ProjectSchema, StoryMetadata

    proj = ProjectSchema(story=StoryMetadata(title="T", chapters=["ch01"]))
    from manga_pipeline.core.anchors import AnchorStore

    store = AnchorStore(proj)
    orphan_anchor = store.create_anchor("panel", "p_gone000000")  # not in layout
    live_anchor = store.create_anchor("panel", "p_aaa111222333")
    (tmp_path / "project.json").write_text(proj.model_dump_json(indent=2), encoding="utf-8")

    res = client.get("/api/anchors/orphaned")
    assert res.status_code == 200
    orphans = {o["anchor"] for o in res.json()["orphaned"]}
    assert orphan_anchor in orphans
    assert live_anchor not in orphans

    # Manual remap
    res = client.post("/api/anchors/remap", json={"anchor_id": orphan_anchor, "new_ai_id": "p_bbb444555666"})
    assert res.status_code == 200

    # Retire
    res = client.post(f"/api/anchors/{live_anchor}/retire")
    assert res.status_code == 200
    proj_after = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    assert proj_after["anchors"][live_anchor]["retired"] is True


def test_hardware_and_providers_endpoints(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)

    res = client.get("/api/hardware")
    assert res.status_code == 200
    assert "has_nvenc" in res.json()

    res = client.get("/api/tts/providers")
    assert res.status_code == 200
    body = res.json()
    assert "edge" in body["providers"]
    assert body["fallback"] == "local-silence"


def test_reconcile_endpoint_with_new_version(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    _write_layout(tmp_path)

    # Seed anchors from v1
    from manga_pipeline.core.anchors import AnchorStore
    from manga_pipeline.core.schemas.project_schema import ProjectSchema, StoryMetadata

    proj = ProjectSchema(story=StoryMetadata(title="T", chapters=["ch01"]))
    proj.active_artifacts["ch01"] = {"layout": 1}
    store = AnchorStore(proj)
    a1 = store.create_anchor("panel", "p_aaa111222333")
    store.create_anchor("panel", "p_bbb444555666")
    (tmp_path / "project.json").write_text(proj.model_dump_json(indent=2), encoding="utf-8")

    # New layout v2: same panel 1 bbox but new ID (simulates re-run), panel 2 identical
    layout_v2 = {
        "schema_version": 1,
        "stage": "layout",
        "chapter_id": "ch01",
        "artifact_version": 2,
        "manifest": {"engine": "test", "engine_version": "1.1", "timestamp": "2026-08-30T11:00:00Z", "inputs": []},
        "panels": [
            {
                "id": "p_newid1111111",
                "source": {"image": "pages/001.png", "bbox": [2, 2, 100, 100]},
                "reading_order": 1,
                "text_regions": [],
            },
            {
                "id": "p_bbb444555666",
                "source": {"image": "pages/001.png", "bbox": [0, 120, 100, 100]},
                "reading_order": 2,
                "text_regions": [],
            },
        ],
    }
    (tmp_path / "artifacts" / "layout.ch01.v2.json").write_text(json.dumps(layout_v2), encoding="utf-8")

    res = client.post("/api/reconcile/layout", json={"chapter_id": "ch01", "new_version": 2})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    # Panel 1 remapped by IoU, panel 2 exact match
    remapped_anchors = [r["anchor"] for r in body["remapped"]]
    assert a1 in remapped_anchors
    proj_after = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    assert proj_after["anchors"][a1]["current"] == "p_newid1111111"
    assert proj_after["active_artifacts"]["ch01"]["layout"] == 2
