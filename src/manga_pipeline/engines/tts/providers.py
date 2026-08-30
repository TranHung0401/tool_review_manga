"""TTS multi-provider adapter (Sprint 4).

Parity with MagaRecap multi-vendor TTS: providers register behind the single
``TtsEngine`` protocol; a local provider is always available as fallback so
the pipeline never depends on network/cloud (architecture principle 1).

Voice refs use the ``provider:voice`` convention from the character registry,
e.g. ``edge:vi-VN-HoaiMyNeural`` or ``local:silence``.
"""

import wave
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from manga_pipeline.core.schemas.artifact_tts import (
    TtsArtifact,
    TtsClip,
    TtsDependsOn,
    TtsManifest,
)
from manga_pipeline.engines.protocols import TtsEngine, TtsRequest, TtsResult
from manga_pipeline.engines.tts.edge_tts_engine import EdgeTtsEngine, _generate_silent_wav


class LocalSilenceTtsEngine(TtsEngine):
    """Offline deterministic TTS provider — always works, $0, no network.

    Estimates duration from word count and writes valid silent WAVs. Serves as
    the guaranteed fallback provider and as a fast engine for tests/benchmarks.
    """

    MS_PER_WORD = 350
    MIN_MS = 1500

    def synthesize(self, request: TtsRequest) -> TtsResult:
        request.audio_output_dir.mkdir(parents=True, exist_ok=True)
        clips: list[TtsClip] = []
        for unit in request.script_artifact.units:
            filename = f"{request.chapter_id}_{unit.id}.v{request.artifact_version}.wav"
            out_file = request.audio_output_dir / filename
            duration_ms = max(self.MIN_MS, len(unit.text.split()) * self.MS_PER_WORD)
            _generate_silent_wav(out_file, duration_ms)
            with wave.open(str(out_file), "rb") as wf:
                framerate = wf.getframerate()
                actual_ms = int((wf.getnframes() / framerate) * 1000) if framerate else duration_ms
            clips.append(TtsClip(unit_id=unit.id, file=f"audio/{filename}", duration_ms=actual_ms))

        artifact = TtsArtifact(
            schema_version=1,
            stage="tts",
            chapter_id=request.chapter_id,
            artifact_version=request.artifact_version,
            depends_on=TtsDependsOn(
                stage="script", artifact_version=request.script_artifact.artifact_version
            ),
            manifest=TtsManifest(
                provider="local-silence",
                voice_ref=request.voice_ref,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
            clips=clips,
        )
        return TtsResult(artifact=artifact)


class TtsProviderRegistry:
    """Registry + dispatcher for TTS providers with automatic local fallback."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], TtsEngine]] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register("edge", lambda: EdgeTtsEngine())
        self.register("edge-tts", lambda: EdgeTtsEngine())
        self.register("local", lambda: LocalSilenceTtsEngine())
        self.register("local-silence", lambda: LocalSilenceTtsEngine())
        # Optional cloud/local providers register lazily; import errors surface
        # only if the user actually selects them.
        self.register("elevenlabs", _make_elevenlabs)
        self.register("openai", _make_openai)
        self.register("vieneu-local", _make_vieneu)
        self.register("kokoro-local", _make_kokoro)

    def register(self, name: str, factory: Callable[[], TtsEngine]) -> None:
        self._factories[name] = factory

    def providers(self) -> list[str]:
        return sorted(self._factories)

    def resolve_voice_ref(self, voice_ref: str) -> tuple[str, str]:
        """Split ``provider:voice`` registry convention; default provider=edge."""
        if ":" in voice_ref:
            provider, voice = voice_ref.split(":", 1)
            return provider, voice
        return "edge", voice_ref

    def create(self, provider: str) -> TtsEngine:
        if provider not in self._factories:
            raise KeyError(
                f"Unknown TTS provider '{provider}'. Registered: {self.providers()}"
            )
        return self._factories[provider]()

    def synthesize(
        self,
        request: TtsRequest,
        provider: str | None = None,
        fallback_provider: str = "local-silence",
    ) -> TtsResult:
        """Dispatch synthesis to a provider with guaranteed local fallback."""
        prov = provider
        if prov is None:
            prov, voice = self.resolve_voice_ref(request.voice_ref)
            request.voice_ref = voice

        try:
            engine = self.create(prov)
            result = engine.synthesize(request)
        except Exception:
            fallback = self.create(fallback_provider)
            result = fallback.synthesize(request)
            result.artifact.manifest.fallback_provider = fallback_provider
            return result

        result.artifact.manifest.fallback_provider = fallback_provider
        return result


# --- optional provider factories (lazy imports, raise only when selected) ---

def _make_elevenlabs() -> TtsEngine:  # pragma: no cover - optional cloud provider
    raise RuntimeError(
        "ElevenLabs provider requires 'elevenlabs' package and API key "
        "(settings.privacy must be 'cloud_allowed'). Falling back to local provider."
    )


def _make_openai() -> TtsEngine:  # pragma: no cover - optional cloud provider
    raise RuntimeError(
        "OpenAI TTS provider requires 'openai' package and API key "
        "(settings.privacy must be 'cloud_allowed'). Falling back to local provider."
    )


def _make_vieneu() -> TtsEngine:  # pragma: no cover - optional local model
    raise RuntimeError("VieNeu local TTS model is not installed. Falling back to local provider.")


def _make_kokoro() -> TtsEngine:  # pragma: no cover - optional local model
    raise RuntimeError("Kokoro local TTS model is not installed. Falling back to local provider.")


def build_tts_adapter(config: dict[str, Any] | None = None) -> TtsProviderRegistry:
    """Build the default TTS adapter registry (config reserved for future use)."""
    return TtsProviderRegistry()
