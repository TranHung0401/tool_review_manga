"""Sprint 3: translate script mode tests (local, $0 cloud, 1-1 bubble)."""

from manga_pipeline.core.schemas.artifact_ocr import (
    OcrArtifact,
    OcrDependsOn,
    OcrManifest,
    OcrPanel,
    OcrText,
)
from manga_pipeline.engines.protocols import ScriptRequest
from manga_pipeline.engines.script.translate_engine import (
    TranslateScriptEngine,
    glossary_translator,
)


def _ocr() -> OcrArtifact:
    return OcrArtifact(
        chapter_id="ch01",
        artifact_version=2,
        depends_on=OcrDependsOn(stage="layout", artifact_version=1),
        manifest=OcrManifest(engine="rapidocr", model="v4", engine_version="1.0", timestamp="2026-08-30T10:00:00Z"),
        panels=[
            OcrPanel(
                id="p_aaa111222333",
                texts=[
                    OcrText(id="t_txt111111111", original="Hello world", text_type="dialogue", reading_order=1),
                    OcrText(id="t_txt222222222", original="BOOM", text_type="sfx", reading_order=2),
                ],
            ),
            OcrPanel(id="p_bbb444555666", texts=[]),  # empty panel
        ],
    )


def test_glossary_translator_applies_terms() -> None:
    out = glossary_translator("Hello world", "vi", {"Hello": "Xin chào", "world": "thế giới"})
    assert out == "Xin chào thế giới"


def test_glossary_translator_longest_term_first() -> None:
    out = glossary_translator("Fire Dragon Slayer", "vi", {"Fire Dragon": "Hỏa Long", "Fire": "Lửa"})
    assert out == "Hỏa Long Slayer"


def test_translate_mode_one_to_one_with_traceability() -> None:
    engine = TranslateScriptEngine()
    result = engine.produce(
        ScriptRequest(
            chapter_id="ch01",
            mode="translate",
            ocr_artifact=_ocr(),
            target_language="vi",
            glossary={"Hello world": "Xin chào thế giới"},
        )
    )
    art = result.artifact

    assert art.manifest.mode == "translate"
    assert art.manifest.model == "phi-4-mini"
    assert art.manifest.quantization == "Q4_K_M"
    assert art.depends_on.artifact_version == 2

    # 1-1 bubble units with source_text_ids traceability
    unit1 = art.units[0]
    assert unit1.text == "Xin chào thế giới"
    assert unit1.source_text_ids == ["t_txt111111111"]
    assert unit1.type == "dialogue"

    unit2 = art.units[1]
    assert unit2.type == "sfx"
    assert unit2.source_text_ids == ["t_txt222222222"]

    # Empty panel still gets a narration unit (panel-complete)
    empty_units = [u for u in art.units if u.panel_id == "p_bbb444555666"]
    assert len(empty_units) == 1
    assert empty_units[0].type == "narration"


def test_translate_units_same_schema_as_other_modes() -> None:
    """DoD (f): all 3 modes produce the same unit schema; IDs stable on re-run."""
    engine = TranslateScriptEngine()
    req = ScriptRequest(chapter_id="ch01", mode="translate", ocr_artifact=_ocr(), glossary={})
    run1 = engine.produce(req).artifact
    run2 = engine.produce(req).artifact

    assert [u.id for u in run1.units] == [u.id for u in run2.units]
    for u in run1.units:
        assert u.id.startswith("s_")
        assert u.panel_id.startswith("p_")
        assert u.type in ("narration", "dialogue", "sfx")


def test_translate_custom_backend_injection() -> None:
    """Backends are pluggable per capability protocol."""
    calls = []

    def fake_llm(text: str, lang: str, glossary: dict[str, str]) -> str:
        calls.append(text)
        return f"[{lang}] {text}"

    engine = TranslateScriptEngine(translator=fake_llm, model_name="qwen3-4b")
    result = engine.produce(
        ScriptRequest(chapter_id="ch01", mode="translate", ocr_artifact=_ocr(), target_language="en")
    )
    assert result.artifact.manifest.model == "qwen3-4b"
    assert result.artifact.units[0].text == "[en] Hello world"
    assert len(calls) == 2  # two non-empty OCR texts
