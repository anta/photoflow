from unittest.mock import patch

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from photoflow.indexer import index_library
from photoflow.locking import index_lock
from photoflow.models import Photo, ScanRun
from photoflow.scanner import ScanIssue


@pytest.mark.integration
def test_index_add_skip_update_missing_and_restore(settings, engine):
    path = settings.nas_root / "generated.jpg"
    Image.new("RGB", (100, 60), "red").save(path)
    assert index_library(settings).added == 1
    with patch("photoflow.indexer.ExifTool.extract", side_effect=AssertionError("must skip")):
        assert index_library(settings).unchanged == 1
    Image.new("RGB", (200, 120), "blue").save(path)
    assert index_library(settings).updated == 1
    with Session(engine) as session:
        photo = session.scalar(select(Photo))
        photo_id = photo.id
        assert photo.width == 200
    path.rename(settings.nas_root / "temporarily.txt")
    assert index_library(settings).missing == 1
    with Session(engine) as session:
        assert session.get(Photo, photo_id).is_missing
    (settings.nas_root / "temporarily.txt").rename(path)
    assert index_library(settings).updated == 1
    with Session(engine) as session:
        assert not session.get(Photo, photo_id).is_missing
        assert len(session.scalars(select(Photo)).all()) == 1
        assert all(run.status == "completed" for run in session.scalars(select(ScanRun)))


@pytest.mark.integration
def test_corrupt_files_do_not_prevent_valid_indexing_and_are_retried(settings, engine):
    Image.new("RGB", (100, 60)).save(settings.nas_root / "valid.jpg")
    corrupt = settings.nas_root / "corrupt.jpg"
    corrupt.write_bytes(b"not an image")
    first = index_library(settings)
    assert (first.added, first.failed, first.status) == (1, 1, "failed")
    Image.new("RGB", (80, 80)).save(corrupt)
    second = index_library(settings)
    assert (second.added, second.unchanged, second.failed) == (1, 1, 0)


@pytest.mark.integration
def test_scan_errors_never_mark_unseen_files_missing(settings, engine):
    Image.new("RGB", (100, 60)).save(settings.nas_root / "valid.jpg")
    index_library(settings)

    def incomplete_scan(_nas, on_error):
        on_error(ScanIssue("inaccessible", "unreadable_entry"))
        return iter(())

    with patch("photoflow.indexer.scan_photos", side_effect=incomplete_scan):
        result = index_library(settings)
    assert result.status == "failed" and result.scan_errors == 1 and result.missing == 0
    with Session(engine) as session:
        assert not session.scalar(select(Photo)).is_missing


def test_only_one_index_process_may_run(settings, engine):
    with index_lock(settings), pytest.raises(RuntimeError, match="already running"):
        index_library(settings)


@pytest.mark.integration
def test_force_reextracts_and_interrupted_runs_are_recovered(settings, engine):
    from photoflow.indexer import utc_now

    Image.new("RGB", (100, 60)).save(settings.nas_root / "valid.jpg")
    with Session(engine) as session:
        session.add(ScanRun(id="interrupted", started_at=utc_now(), status="running"))
        session.commit()
    index_library(settings)
    assert index_library(settings, force=True).updated == 1
    with Session(engine) as session:
        assert session.get(ScanRun, "interrupted").status == "failed"


def test_fatal_scan_failure_records_failed_run_without_missing_sweep(settings, engine):
    with (
        patch("photoflow.indexer.scan_photos", side_effect=OSError("NAS disconnected")),
        pytest.raises(OSError),
    ):
        index_library(settings)
    with Session(engine) as session:
        run = session.scalar(select(ScanRun))
        assert run.status == "failed" and run.finished_at is not None
