"""DoD (a): JSON Schema validation tests for all 5 artifacts and project.json."""

import pytest
from pydantic import ValidationError

from manga_pipeline.core.schemas import (
    LayoutArtifact,
    OcrArtifact,
    ProjectSchema,
    ScriptArtifact,
    StoryArtifact,
    TtsArtifact,
)


def test_layout_schema_valid() -> None:
    data = {
        "schema_version": 1,
        "stage": "layout",
        "chapter_id": "ch01",
        "artifact_version": 1,
        "manifest": {
            "engine": "manga-image-translator/detector",
            "engine_version": "0.1.0",
            "timestamp": "2026-08-30T10:00:00Z",
            "inputs": [{"file": "pages/001.png", "sha256": "abc123def456"}],
        },
        "panels": [
            {
                "id": "p_3fa8c1d02b9e",
                "source": {"image": "pages/001.png", "bbox": [100, 200, 700, 400]},
                "reading_order": 1,
                "text_regions": [{"id": "t_9b2e44f01a7c", "bbox": [120, 220, 180, 100], "region_type": "bubble"}],
            }
        ],
    }
    artifact = LayoutArtifact.model_validate(data)
    assert artifact.stage == "layout"
    assert len(artifact.panels) == 1
    assert artifact.panels[0].id == "p_3fa8c1d02b9e"


def test_ocr_schema_valid() -> None:
    data = {
        "schema_version": 1,
        "stage": "ocr",
        "chapter_id": "ch01",
        "artifact_version": 2,
        "depends_on": {"stage": "layout", "artifact_version": 1},
        "manifest": {
            "engine": "manga-ocr",
            "model": "kha-white/manga-ocr-base",
            "engine_version": "0.1.11",
            "timestamp": "2026-08-30T10:05:00Z",
        },
        "panels": [
            {
                "id": "p_3fa8c1d02b9e",
                "cleaned_image": "cleaned/001.png",
                "texts": [
                    {
                        "id": "t_9b2e44f01a7c",
                        "original": "こんにちは",
                        "text_type": "dialogue",
                        "reading_order": 1,
                        "confidence": 0.94,
                    }
                ],
            }
        ],
    }
    artifact = OcrArtifact.model_validate(data)
    assert artifact.stage == "ocr"
    assert artifact.panels[0].texts[0].original == "こんにちは"


def test_script_schema_all_3_modes() -> None:
    for mode in ["manual_script", "translate", "ai_narrate"]:
        data = {
            "schema_version": 1,
            "stage": "script",
            "chapter_id": "ch01",
            "artifact_version": 4,
            "depends_on": {"stage": "ocr", "artifact_version": 2},
            "manifest": {
                "mode": mode,
                "engine": "test_engine",
                "timestamp": "2026-08-30T10:10:00Z",
            },
            "units": [
                {
                    "id": "s_ab12cd34ef56",
                    "panel_id": "p_3fa8c1d02b9e",
                    "seq": 1,
                    "type": "narration",
                    "text": "Lời kể mẫu",
                    "source_text_ids": [],
                }
            ],
        }
        artifact = ScriptArtifact.model_validate(data)
        assert artifact.manifest.mode == mode
        assert artifact.units[0].text == "Lời kể mẫu"


def test_tts_schema_valid() -> None:
    data = {
        "schema_version": 1,
        "stage": "tts",
        "chapter_id": "ch01",
        "artifact_version": 7,
        "depends_on": {"stage": "script", "artifact_version": 4},
        "manifest": {
            "provider": "edge-tts",
            "voice_ref": "vi-VN-HoaiMyNeural",
            "timestamp": "2026-08-30T10:15:00Z",
        },
        "clips": [
            {
                "unit_id": "s_ab12cd34ef56",
                "file": "audio/ch01_s_ab12cd34ef56.v7.wav",
                "duration_ms": 5100,
            }
        ],
    }
    artifact = TtsArtifact.model_validate(data)
    assert artifact.stage == "tts"
    assert artifact.clips[0].duration_ms == 5100


def test_story_schema_reserved() -> None:
    data = {
        "schema_version": 1,
        "stage": "story",
        "chapter_id": "ch01",
        "artifact_version": 1,
        "manifest": {"engine": "reserved_story_engine", "timestamp": "2026-08-30T10:00:00Z"},
        "beats": [{"type": "hook", "panel_ids": ["p_001"], "description": "Opening hook"}],
    }
    artifact = StoryArtifact.model_validate(data)
    assert artifact.stage == "story"
    assert len(artifact.beats) == 1


def test_project_schema_enforces_anchors() -> None:
    valid_data = {
        "schema_version": 1,
        "story": {"title": "Manga Title", "chapters": ["ch01"]},
        "anchors": {
            "pa_000001": {
                "kind": "panel",
                "current": "p_3fa8c1d02b9e",
                "history": ["p_3fa8c1d02b9e"],
            },
            "ta_000002": {
                "kind": "text",
                "current": "t_9b2e44f01a7c",
                "history": ["t_9b2e44f01a7c"],
            },
            "sa_000003": {
                "kind": "unit",
                "current": "s_ab12cd34ef56",
                "history": ["s_ab12cd34ef56"],
            },
        },
        "layout_overrides": {
            "ch01": {
                "deleted_panels": ["pa_000001"],
            }
        },
        "overrides": {"ta_000002": {"text": "Sửa thoại tiếng Việt", "reviewed": True}},
        "sequence": {
            "video_tracks": [
                {
                    "clips": [
                        {
                            "panel_ref": "pa_000001",
                            "start_ms": 0,
                            "duration_ms": 5000,
                        }
                    ]
                }
            ],
            "audio_tracks": [
                {
                    "clips": [
                        {
                            "audio_ref": "sa_000003",
                            "start_ms": 0,
                            "synced_duration_ms": 4800,
                            "synced_artifact_version": 7,
                        }
                    ]
                }
            ],
        },
    }
    project = ProjectSchema.model_validate(valid_data)
    assert "pa_000001" in project.anchors


def test_project_schema_rejects_raw_ai_ids_in_overrides() -> None:
    invalid_data = {
        "schema_version": 1,
        "story": {"title": "Test", "chapters": ["ch01"]},
        "anchors": {},
        "overrides": {"t_raw_ai_id_123": {"text": "Invalid override using AI ID"}},
    }
    with pytest.raises(ValidationError):
        ProjectSchema.model_validate(invalid_data)


def test_project_schema_rejects_raw_ai_ids_in_video_clips() -> None:
    invalid_data = {
        "schema_version": 1,
        "story": {"title": "Test", "chapters": ["ch01"]},
        "sequence": {
            "video_tracks": [
                {
                    "clips": [
                        {
                            "panel_ref": "p_raw_ai_id_123",  # Must be pa_...
                            "start_ms": 0,
                            "duration_ms": 5000,
                        }
                    ]
                }
            ]
        },
    }
    with pytest.raises(ValidationError):
        ProjectSchema.model_validate(invalid_data)


def test_real_sample_fixtures_valid() -> None:
    """Validate all real artifacts generated from ch_sample against Pydantic schemas."""
    import json
    from pathlib import Path

    fixture_dir = Path("tests/fixtures/ch_sample")
    if not (fixture_dir / "layout.ch_sample.v1.json").exists():
        pytest.skip("ch_sample fixtures not present")

    # 1. Validate layout
    layout_data = json.loads((fixture_dir / "layout.ch_sample.v1.json").read_text(encoding="utf-8"))
    layout_art = LayoutArtifact.model_validate(layout_data)
    assert len(layout_art.panels) > 0

    # 2. Validate ocr
    ocr_data = json.loads((fixture_dir / "ocr.ch_sample.v1.json").read_text(encoding="utf-8"))
    ocr_art = OcrArtifact.model_validate(ocr_data)
    assert len(ocr_art.panels) > 0

    # 3. Validate script
    script_data = json.loads((fixture_dir / "script.ch_sample.v1.json").read_text(encoding="utf-8"))
    script_art = ScriptArtifact.model_validate(script_data)
    assert len(script_art.units) > 0

    # 4. Validate tts
    tts_data = json.loads((fixture_dir / "tts.ch_sample.v1.json").read_text(encoding="utf-8"))
    tts_art = TtsArtifact.model_validate(tts_data)
    assert len(tts_art.clips) > 0

    # 5. Validate project.json
    proj_data = json.loads((fixture_dir / "project.json").read_text(encoding="utf-8"))
    proj = ProjectSchema.model_validate(proj_data)
    assert len(proj.anchors) > 0
