"""Translate script engine (Sprint 3 — parity mode, 100% local).

Translates OCR bubbles 1-1 into script units using a local LLM backend
(llama.cpp + Phi-4-mini as the *suggested* default per architecture.md).
The engine follows the capability protocol: backends are pluggable, and a
glossary-based passthrough backend guarantees the pipeline always works
offline with $0 cloud cost even when no LLM binary is installed.
"""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from manga_pipeline.core.ids import unit_id
from manga_pipeline.core.schemas.artifact_script import (
    ScriptArtifact,
    ScriptDependsOn,
    ScriptManifest,
    ScriptUnit,
)
from manga_pipeline.engines.protocols import ScriptEngine, ScriptRequest, ScriptResult

TranslatorFn = Callable[[str, str, dict[str, str]], str]


def glossary_translator(text: str, target_language: str, glossary: dict[str, str]) -> str:
    """Deterministic local fallback: apply glossary term substitutions.

    Guarantees translate mode never blocks the pipeline when no local LLM is
    available (architecture principle 1: local-first, no mandatory cloud).
    """
    result = text
    for term, replacement in sorted(glossary.items(), key=lambda kv: -len(kv[0])):
        if term:
            result = result.replace(term, replacement)
    return result


class LlamaCppTranslator:
    """llama.cpp local LLM translator backend (optional dependency)."""

    def __init__(
        self,
        model_path: str,
        n_gpu_layers: int = -1,
        n_ctx: int = 4096,
    ) -> None:
        try:
            from llama_cpp import Llama  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "llama-cpp-python is not installed. Install it or use the glossary fallback backend."
            ) from e
        self._llm = Llama(model_path=model_path, n_gpu_layers=n_gpu_layers, n_ctx=n_ctx, verbose=False)

    def __call__(self, text: str, target_language: str, glossary: dict[str, str]) -> str:
        glossary_block = "\n".join(f"- {k} => {v}" for k, v in glossary.items())
        prompt = (
            f"Translate the following comic dialogue to {target_language}. "
            f"Keep it natural and concise. Respect this glossary:\n{glossary_block}\n\n"
            f"Text: {text}\nTranslation:"
        )
        out = self._llm(prompt, max_tokens=256, temperature=0.2, stop=["\n\n"])
        return str(out["choices"][0]["text"]).strip() or text


class TranslateScriptEngine(ScriptEngine):
    """Implements ScriptEngine for translate mode: 1-1 bubble translation.

    Every OCR text becomes one script unit with ``source_text_ids`` traceable
    back to the OCR artifact — units share the exact schema of all 3 modes.
    """

    def __init__(
        self,
        translator: TranslatorFn | None = None,
        model_name: str = "phi-4-mini",
        quantization: str = "Q4_K_M",
        gpu_layers: str | int = "auto",
        options: dict[str, Any] | None = None,
    ) -> None:
        self.translator: TranslatorFn = translator or glossary_translator
        self.model_name = model_name
        self.quantization = quantization
        self.gpu_layers = gpu_layers
        self.options = options or {}
        self._engine_name = "llama_cpp" if translator is not None else "glossary_local"

    def produce(self, request: ScriptRequest) -> ScriptResult:
        units: list[ScriptUnit] = []

        for panel in request.ocr_artifact.panels:
            seq = 0
            texts = sorted(panel.texts, key=lambda t: t.reading_order)
            for t in texts:
                original = (t.original or "").strip()
                if not original:
                    continue
                seq += 1
                unit_type = t.text_type if t.text_type in ("narration", "dialogue", "sfx") else "dialogue"
                translated = self.translator(original, request.target_language, request.glossary)
                uid = unit_id(panel.id, seq, unit_type)
                units.append(
                    ScriptUnit(
                        id=uid,
                        panel_id=panel.id,
                        seq=seq,
                        type=unit_type,  # type: ignore[arg-type]
                        text=translated,
                        source_text_ids=[t.id],
                        speaker_id_hint=t.speaker_id_hint,
                    )
                )
            if seq == 0:
                # Panel without any OCR text still gets one narration unit so
                # downstream TTS/timeline stays panel-complete.
                uid = unit_id(panel.id, 1, "narration")
                units.append(
                    ScriptUnit(
                        id=uid,
                        panel_id=panel.id,
                        seq=1,
                        type="narration",
                        text=f"Khung tranh {panel.id[-4:]} không có lời thoại.",
                        source_text_ids=[],
                        speaker_id_hint=None,
                    )
                )

        manifest = ScriptManifest(
            mode="translate",
            engine=self._engine_name,
            model=self.model_name,
            quantization=self.quantization,
            gpu_layers=self.gpu_layers,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        artifact = ScriptArtifact(
            schema_version=1,
            stage="script",
            chapter_id=request.chapter_id,
            artifact_version=1,
            depends_on=ScriptDependsOn(
                stage="ocr", artifact_version=request.ocr_artifact.artifact_version
            ),
            manifest=manifest,
            units=units,
        )
        return ScriptResult(artifact=artifact)
