"""Incrementally index metadata while leaving the photo tree untouched."""

import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from photoflow.config import Settings
from photoflow.db import bind_library, create_db_engine, require_current_schema
from photoflow.locking import index_lock
from photoflow.metadata import ExifTool, MetadataError
from photoflow.models import Photo, ScanRun
from photoflow.nas import NasRoot, UnsafePathError
from photoflow.scanner import PhotoFile, ScanIssue, scan_photos


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass
class IndexResult:
    run_id: str
    status: str = "running"
    discovered: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    missing: int = 0
    scan_errors: int = 0


def _index_one(
    session: Session, nas: NasRoot, tool: ExifTool, item: PhotoFile, run_id: str, force: bool
) -> str:
    photo = session.scalar(select(Photo).where(Photo.relative_path == item.relative_path))
    if photo is not None:
        photo.last_seen_scan = run_id
        photo.is_missing = False
        if (
            not force
            and photo.index_error is None
            and (photo.size_bytes, photo.mtime_ns, photo.ctime_ns) == item.signature
        ):
            session.commit()
            return "unchanged"
    try:
        with nas.open_photo(item.relative_path) as source:
            opened = PhotoFile.from_stat(item.relative_path, os.fstat(source.fileno()))
            if opened.signature != item.signature:
                raise MetadataError("file_changed")
            metadata = tool.extract(source)
            after = PhotoFile.from_stat(item.relative_path, os.fstat(source.fileno()))
            if after.signature != opened.signature:
                raise MetadataError("file_changed")
    except (MetadataError, OSError, UnsafePathError) as error:
        if photo is not None:
            photo.index_error = (
                str(error) if isinstance(error, MetadataError) else "file_unreadable"
            )
        session.commit()
        return "failed"

    outcome = "added" if photo is None else "updated"
    values = asdict(metadata) | {
        "relative_path": item.relative_path,
        "size_bytes": item.size_bytes,
        "mtime_ns": item.mtime_ns,
        "ctime_ns": item.ctime_ns,
        "indexed_at": utc_now(),
        "last_seen_scan": run_id,
        "is_missing": False,
        "index_error": None,
    }
    if photo is None:
        session.add(Photo(**values))
    else:
        for key, value in values.items():
            setattr(photo, key, value)
    session.commit()
    return outcome


def _finish_run(session: Session, result: IndexResult) -> None:
    run = session.get(ScanRun, result.run_id)
    assert run is not None
    for field in ("status", "discovered", "added", "updated", "unchanged", "failed", "missing"):
        setattr(run, field, getattr(result, field))
    run.finished_at = utc_now()
    session.commit()


def index_library(settings: Settings, *, force: bool = False) -> IndexResult:
    with index_lock(settings):
        # Fail before creating a scan run if a required dependency is missing.
        tool = ExifTool(settings)
        nas = NasRoot(settings.nas_root)
        engine = create_db_engine(settings)
        try:
            require_current_schema(engine)
            with Session(engine, expire_on_commit=False) as session:
                bind_library(session, settings)
                # The process lock proves older running entries were interrupted.
                session.execute(
                    update(ScanRun)
                    .where(ScanRun.status == "running")
                    .values(status="failed", finished_at=utc_now())
                )
                result = IndexResult(run_id=uuid4().hex)
                session.add(ScanRun(id=result.run_id, started_at=utc_now(), status="running"))
                session.commit()

                def on_scan_error(_issue: ScanIssue) -> None:
                    result.scan_errors += 1
                    result.failed += 1

                try:
                    for item in scan_photos(nas, on_error=on_scan_error):
                        result.discovered += 1
                        outcome = _index_one(session, nas, tool, item, result.run_id, force)
                        setattr(result, outcome, getattr(result, outcome) + 1)
                    # A partial traversal must never hide photos in unreadable directories.
                    if result.scan_errors == 0:
                        changed = session.execute(
                            update(Photo)
                            .where(
                                Photo.last_seen_scan != result.run_id, Photo.is_missing.is_(False)
                            )
                            .values(is_missing=True)
                        )
                        result.missing = changed.rowcount
                    result.status = "completed" if result.failed == 0 else "failed"
                    _finish_run(session, result)
                except BaseException:
                    session.rollback()
                    result.status = "failed"
                    _finish_run(session, result)
                    raise
                return result
        finally:
            engine.dispose()
