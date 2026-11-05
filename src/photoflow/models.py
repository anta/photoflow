"""SQLAlchemy models for a single NAS library and its indexing history."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Library(Base):
    __tablename__ = "library"
    __table_args__ = (CheckConstraint("id = 1", name="single_library"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    root_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class ScanRun(Base):
    __tablename__ = "scan_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="scan_status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Photo(Base):
    __tablename__ = "photos"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="photo_size"),
        CheckConstraint("width IS NULL OR width > 0", name="photo_width"),
        CheckConstraint("height IS NULL OR height > 0", name="photo_height"),
        CheckConstraint("latitude IS NULL OR latitude BETWEEN -90 AND 90", name="photo_latitude"),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180", name="photo_longitude"
        ),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    relative_path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mtime_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ctime_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    format: Mapped[str | None] = mapped_column(String(16))
    mime_type: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    orientation: Mapped[int | None] = mapped_column(Integer)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    captured_at_offset: Mapped[str | None] = mapped_column(String(6))
    camera_make: Mapped[str | None] = mapped_column(String(128))
    camera_model: Mapped[str | None] = mapped_column(String(128))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    indexed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_scan: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    is_missing: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)
    index_error: Mapped[str | None] = mapped_column(String(32))
