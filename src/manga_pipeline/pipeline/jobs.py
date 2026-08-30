"""Job execution system with per-item checkpointing, idempotency, and engine locking."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


class EngineLockMismatchError(Exception):
    """Raised when attempting to resume a job with a different engine, model, or version."""


@dataclass
class EngineLock:
    engine: str
    model: str = ""
    engine_version: str = ""

    def matches(self, other: "EngineLock") -> bool:
        return self.engine == other.engine and self.model == other.model and self.engine_version == other.engine_version


@dataclass
class JobItemState:
    status: Literal["pending", "running", "done", "failed"] = "pending"
    error: str | None = None
    attempts: int = 0
    output_meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobState:
    job_id: str
    type: Literal["layout", "ocr", "script", "tts"]
    chapter_id: str
    status: Literal["pending", "running", "success", "failed"]
    engine_lock: EngineLock
    output_artifact: str
    items_total: int
    items: dict[str, JobItemState] = field(default_factory=dict)
    cost_actual_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobState":
        lock_data = data.get("engine_lock", {})
        engine_lock = EngineLock(**lock_data)
        items_data = data.get("items", {})
        items = {k: JobItemState(**v) for k, v in items_data.items()}

        return cls(
            job_id=data["job_id"],
            type=data["type"],
            chapter_id=data["chapter_id"],
            status=data["status"],
            engine_lock=engine_lock,
            output_artifact=data["output_artifact"],
            items_total=data["items_total"],
            items=items,
            cost_actual_usd=data.get("cost_actual_usd", 0.0),
        )


class JobRunner:
    """Manages job persistence, checkpointing, resume, and atomic artifact finalization."""

    @staticmethod
    def save_checkpoint(job: JobState, job_dir: Path) -> Path:
        """Save job state JSON checkpoint atomically."""
        job_dir.mkdir(parents=True, exist_ok=True)
        job_file = job_dir / f"{job.job_id}.json"
        tmp_file = job_dir / f"{job.job_id}.json.tmp"

        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(job.to_dict(), f, indent=2, ensure_ascii=False)

        # Atomic replace
        tmp_file.replace(job_file)
        return job_file

    @staticmethod
    def load_checkpoint(job_file: Path) -> JobState:
        """Load job state from checkpoint file."""
        if not job_file.exists():
            raise FileNotFoundError(f"Job file '{job_file}' not found.")
        with open(job_file, encoding="utf-8") as f:
            data = json.load(f)
        return JobState.from_dict(data)

    @staticmethod
    def resume_job(job: JobState, active_engine_lock: EngineLock) -> JobState:
        """Validate engine lock before resuming an incomplete job."""
        if not job.engine_lock.matches(active_engine_lock):
            raise EngineLockMismatchError(
                f"Cannot resume job '{job.job_id}'. Expected engine lock {job.engine_lock}, "
                f"but got active {active_engine_lock}."
            )
        job.status = "running"
        return job

    @staticmethod
    def get_pending_items(job: JobState) -> list[str]:
        """Return list of item IDs that still need processing (pending or failed)."""
        return [item_id for item_id, state in job.items.items() if state.status in ("pending", "failed")]

    @staticmethod
    def atomic_finalize_artifact(tmp_artifact_path: Path, target_artifact_path: Path) -> None:
        """Atomically rename .tmp file to final artifact destination."""
        if not tmp_artifact_path.exists():
            raise FileNotFoundError(f"Temporary artifact '{tmp_artifact_path}' does not exist.")
        target_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_artifact_path.replace(target_artifact_path)
