"""Sprint 4: TTS multi-provider adapter tests (registry + guaranteed fallback)."""

from pathlib import Path

from manga_pipeline.core.schemas.artifact_script import (
    ScriptArtifact,
    ScriptDependsOn,
    ScriptManifest,
    ScriptUnit,
)
from manga_pipeline.engines.protocols import TtsRequest
from manga_pipeline.engines.tts.providers import (
    LocalSilenceTtsEngine,
    TtsProviderRegistry,
)


def _script() -> ScriptArtifact:
    return ScriptArtifact(
        chapter_id="ch01",
        artifact_version=1,
        depends_on=ScriptDependsOn(stage="ocr", artifact_version=1),
        manifest=ScriptManifest(mode="manual_script", engine="manual_import", timestamp="2026-08-30T10:00:00Z"),
        units=[
            ScriptUnit(id="s_unit00000001", panel_id="p_aaa111222333", seq=1, type="narration", text="Một hai ba bốn năm"),
        ],
    )


def test_registry_lists_expected_providers() -> None:
    reg = TtsProviderRegistry()
    provs = reg.providers()
    for expected in ("edge", "edge-tts", "local", "local-silence", "elevenlabs", "openai", "vieneu-local", "kokoro-local"):
        assert expected in provs


def test_voice_ref_convention_parsing() -> None:
    reg = TtsProviderRegistry()
    assert reg.resolve_voice_ref("edge:vi-VN-HoaiMyNeural") == ("edge", "vi-VN-HoaiMyNeural")
    assert reg.resolve_voice_ref("elevenlabs:rachel") == ("elevenlabs", "rachel")
    # No prefix -> default provider edge
    assert reg.resolve_voice_ref("vi-VN-HoaiMyNeural") == ("edge", "vi-VN-HoaiMyNeural")


def test_local_silence_engine_produces_valid_artifact(tmp_path: Path) -> None:
    engine = LocalSilenceTtsEngine()
    result = engine.synthesize(
        TtsRequest(
            chapter_id="ch01",
            script_artifact=_script(),
            audio_output_dir=tmp_path,
            artifact_version=3,
            voice_ref="local:silence",
        )
    )
    art = result.artifact
    assert art.manifest.provider == "local-silence"
    assert len(art.clips) == 1
    clip = art.clips[0]
    # Versioned filename (idempotent re-runs never overwrite older versions)
    assert clip.file.endswith(".v3.wav")
    assert clip.duration_ms >= 1500
    assert (tmp_path / f"ch01_{art.clips[0].unit_id}.v3.wav").exists()


def test_unavailable_provider_falls_back_to_local(tmp_path: Path) -> None:
    """Architecture: local fallback always works, cloud never a hard dependency."""
    reg = TtsProviderRegistry()
    result = reg.synthesize(
        TtsRequest(
            chapter_id="ch01",
            script_artifact=_script(),
            audio_output_dir=tmp_path,
            artifact_version=1,
            voice_ref="rachel",
        ),
        provider="elevenlabs",  # not installed -> must fall back
    )
    assert result.artifact.manifest.provider == "local-silence"
    assert result.artifact.manifest.fallback_provider == "local-silence"
    assert len(result.artifact.clips) == 1


def test_unknown_provider_raises_from_create() -> None:
    reg = TtsProviderRegistry()
    try:
        reg.create("nonexistent-tts")
        raise AssertionError("should have raised KeyError")
    except KeyError:
        pass
