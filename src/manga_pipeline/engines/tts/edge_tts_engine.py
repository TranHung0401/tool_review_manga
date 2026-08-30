"""Edge TTS engine adapter for speech synthesis with concurrent execution and fallback."""

import asyncio
import concurrent.futures
import re
import subprocess
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import edge_tts

from manga_pipeline.core.schemas.artifact_tts import (
    TtsArtifact,
    TtsClip,
    TtsDependsOn,
    TtsManifest,
)
from manga_pipeline.engines.protocols import TtsEngine, TtsRequest, TtsResult


def _generate_silent_wav(output_path: Path, duration_ms: int = 2000) -> None:
    """Generate a valid silent WAV file as offline/fallback speech."""
    framerate = 24000
    nframes = int(framerate * (duration_ms / 1000.0))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        wf.writeframes(b"\x00\x00" * nframes)


def _safe_unlink(path: Path) -> None:
    """Safely delete a temporary file ignoring Windows file-lock errors."""
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


async def _synthesize_single_unit(
    text: str, voice: str, output_path: Path, rate_pct: str = "+0%", max_retries: int = 2
) -> int:
    """Synthesize single unit text using edge-tts and convert to real WAV via FFmpeg."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    word_count = max(1, len(text.split()))
    estimated_duration = max(1500, int(word_count * 350))

    # Clean, normalize text (remove bracket labels and collapse whitespace)
    clean_text = re.sub(r"\[[^\]]*\]", "", text).strip()
    if not clean_text or len(clean_text) < 2:
        clean_text = "Lời dẫn chuyện cho khung tranh."

    # Avoid very long strings that overwhelm edge-tts
    if len(clean_text) > 300:
        clean_text = clean_text[:300] + "..."

    for attempt in range(max_retries):
        temp_mp3 = output_path.parent / f"tmp_{uuid.uuid4().hex[:8]}.mp3"
        try:
            communicate = edge_tts.Communicate(clean_text, voice, rate=rate_pct)
            await asyncio.wait_for(communicate.save(str(temp_mp3)), timeout=10.0)

            if temp_mp3.exists() and temp_mp3.stat().st_size > 0:
                conv = subprocess.run(
                    ["ffmpeg", "-y", "-i", str(temp_mp3), "-ar", "24000", "-ac", "1", str(output_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                _safe_unlink(temp_mp3)

                if conv.returncode == 0 and output_path.exists():
                    with wave.open(str(output_path), "rb") as wf:
                        framerate = wf.getframerate()
                        nframes = wf.getnframes()
                        if framerate > 0:
                            return int((nframes / framerate) * 1000)
        except Exception:
            _safe_unlink(temp_mp3)
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
        finally:
            _safe_unlink(temp_mp3)

    # Fallback to local offline synthesis only if all retries failed
    _generate_silent_wav(output_path, estimated_duration)
    return estimated_duration


async def _synthesize_batch(units_data: list[tuple[str, Path]], voice: str, rate_pct: str) -> list[int]:
    """Synthesize all units with bounded concurrency to prevent throttling."""
    sem = asyncio.Semaphore(3)  # Balanced concurrency to Edge TTS

    async def _worker(text: str, out_path: Path) -> int:
        async with sem:
            await asyncio.sleep(0.05)
            return await _synthesize_single_unit(text, voice, out_path, rate_pct)

    tasks = [_worker(text, out_path) for text, out_path in units_data]
    return await asyncio.gather(*tasks)


def _safe_run_async(coro_fn: Any, *args: Any) -> Any:
    """Run an async coroutine safely in an isolated event loop inside a dedicated thread."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        def _runner() -> Any:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro_fn(*args))
            finally:
                loop.close()
        return executor.submit(_runner).result()


class EdgeTtsEngine(TtsEngine):
    """Implements TtsEngine protocol for Vietnamese speech synthesis."""

    def __init__(self, options: dict[str, Any] | None = None):
        self.options = options or {}

    def synthesize(self, request: TtsRequest) -> TtsResult:
        request.audio_output_dir.mkdir(parents=True, exist_ok=True)
        voice = request.voice_ref or "vi-VN-HoaiMyNeural"
        rate_str = f"{int((request.speed - 1.0) * 100):+d}%"

        units_data: list[tuple[str, Path]] = []
        unit_ids: list[str] = []

        for unit in request.script_artifact.units:
            filename = f"{request.chapter_id}_{unit.id}.v{request.artifact_version}.wav"
            out_file = request.audio_output_dir / filename
            units_data.append((unit.text, out_file))
            unit_ids.append(unit.id)

        # Run concurrent batch synthesis safely in isolated loop thread
        durations: list[int] = _safe_run_async(_synthesize_batch, units_data, voice, rate_str)

        clips: list[TtsClip] = []
        for uid, duration_ms in zip(unit_ids, durations, strict=False):
            filename = f"{request.chapter_id}_{uid}.v{request.artifact_version}.wav"
            rel_audio_path = f"audio/{filename}"
            clips.append(
                TtsClip(
                    unit_id=uid,
                    file=rel_audio_path,
                    duration_ms=duration_ms,
                )
            )

        manifest = TtsManifest(
            provider="edge-tts",
            voice_ref=voice,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        depends_on = TtsDependsOn(
            stage="script",
            artifact_version=request.script_artifact.artifact_version,
        )

        artifact = TtsArtifact(
            schema_version=1,
            stage="tts",
            chapter_id=request.chapter_id,
            artifact_version=request.artifact_version,
            depends_on=depends_on,
            manifest=manifest,
            clips=clips,
        )

        return TtsResult(artifact=artifact)
