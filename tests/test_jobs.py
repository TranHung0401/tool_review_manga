"""DoD (d): Job execution system, checkpointing, and engine lock tests."""

from pathlib import Path

import pytest

from manga_pipeline.pipeline.jobs import (
    EngineLock,
    EngineLockMismatchError,
    JobItemState,
    JobRunner,
    JobState,
)


def test_job_state_save_and_load(tmp_path: Path) -> None:
    job = JobState(
        job_id="job_001",
        type="ocr",
        chapter_id="ch01",
        status="running",
        engine_lock=EngineLock(engine="manga-ocr", model="base", engine_version="0.1.11"),
        output_artifact="artifacts/ocr.ch01.v2.json.tmp",
        items_total=3,
        items={
            "p_1": JobItemState(status="done"),
            "p_2": JobItemState(status="running"),
            "p_3": JobItemState(status="pending"),
        },
    )

    job_file = JobRunner.save_checkpoint(job, tmp_path)
    loaded = JobRunner.load_checkpoint(job_file)

    assert loaded.job_id == "job_001"
    assert loaded.items["p_1"].status == "done"
    assert loaded.items["p_3"].status == "pending"
    assert loaded.engine_lock.engine == "manga-ocr"


def test_job_pending_items_filtering() -> None:
    job = JobState(
        job_id="job_002",
        type="layout",
        chapter_id="ch01",
        status="running",
        engine_lock=EngineLock(engine="detector"),
        output_artifact="artifacts/layout.ch01.v1.json.tmp",
        items_total=4,
        items={
            "p_1": JobItemState(status="done"),
            "p_2": JobItemState(status="failed", error="timeout"),
            "p_3": JobItemState(status="pending"),
            "p_4": JobItemState(status="done"),
        },
    )
    pending = JobRunner.get_pending_items(job)
    assert pending == ["p_2", "p_3"]


def test_job_resume_fails_on_engine_mismatch() -> None:
    job = JobState(
        job_id="job_003",
        type="ocr",
        chapter_id="ch01",
        status="failed",
        engine_lock=EngineLock(engine="manga-ocr", model="base", engine_version="0.1.11"),
        output_artifact="artifacts/ocr.ch01.v2.json.tmp",
        items_total=1,
        items={"p_1": JobItemState(status="pending")},
    )

    # Attempt to resume with a different model version
    new_engine = EngineLock(engine="manga-ocr", model="large", engine_version="0.2.0")
    with pytest.raises(EngineLockMismatchError):
        JobRunner.resume_job(job, new_engine)


def test_atomic_finalize_artifact(tmp_path: Path) -> None:
    tmp_artifact = tmp_path / "ocr.tmp"
    target_artifact = tmp_path / "final" / "ocr.json"

    tmp_artifact.write_text('{"schema_version": 1}', encoding="utf-8")
    JobRunner.atomic_finalize_artifact(tmp_artifact, target_artifact)

    assert not tmp_artifact.exists()
    assert target_artifact.exists()
    assert target_artifact.read_text(encoding="utf-8") == '{"schema_version": 1}'
