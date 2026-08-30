"""Hardware detection (Sprint 0): NVENC, CUDA VRAM, RAM, gpu_layers auto."""

import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class HardwareProfile:
    """Detected local hardware capabilities used to auto-tune the pipeline."""

    has_ffmpeg: bool = False
    has_nvenc: bool = False
    gpu_name: str | None = None
    vram_total_mb: int | None = None
    ram_total_mb: int | None = None
    recommended_gpu_layers: int | str = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _detect_nvenc() -> bool:
    if not shutil.which("ffmpeg"):
        return False
    try:
        res = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return "h264_nvenc" in res.stdout
    except Exception:
        return False


def _detect_nvidia_gpu() -> tuple[str | None, int | None]:
    if not shutil.which("nvidia-smi"):
        return None, None
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        line = res.stdout.strip().splitlines()[0] if res.stdout.strip() else ""
        if "," in line:
            name, mem = line.rsplit(",", 1)
            return name.strip(), int(float(mem.strip()))
    except Exception:
        pass
    return None, None


def _detect_ram_mb() -> int | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    try:
        import psutil  # type: ignore[import-not-found]

        return int(psutil.virtual_memory().total // (1024 * 1024))
    except Exception:
        return None


def _recommend_gpu_layers(vram_mb: int | None) -> int | str:
    """gpu_layers auto policy for llama.cpp on constrained VRAM.

    Reference dev machine: 4 GB VRAM (Quadro T1000) — offload partially,
    accept RAM spill (architecture principle 2).
    """
    if vram_mb is None:
        return 0
    if vram_mb >= 12000:
        return -1  # full offload
    if vram_mb >= 8000:
        return 32
    if vram_mb >= 4000:
        return 16
    if vram_mb >= 2000:
        return 8
    return 0


def detect_hardware() -> HardwareProfile:
    """Probe local hardware once; cheap enough to call at startup."""
    gpu_name, vram = _detect_nvidia_gpu()
    return HardwareProfile(
        has_ffmpeg=bool(shutil.which("ffmpeg")),
        has_nvenc=_detect_nvenc(),
        gpu_name=gpu_name,
        vram_total_mb=vram,
        ram_total_mb=_detect_ram_mb(),
        recommended_gpu_layers=_recommend_gpu_layers(vram),
    )
