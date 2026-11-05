"""Public API fields; internal fingerprints and filesystem timestamps stay private."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, field_serializer


class PhotoSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    relative_path: str
    size_bytes: int
    format: str | None
    mime_type: str | None
    width: int | None
    height: int | None
    orientation: int | None
    captured_at: datetime | None
    captured_at_offset: str | None
    indexed_at: datetime
    is_missing: bool
    index_error: str | None

    @field_serializer("indexed_at")
    def serialize_indexed_at(self, value: datetime) -> str:
        return value.replace(tzinfo=UTC).isoformat()


class PhotoDetail(PhotoSummary):
    camera_make: str | None
    camera_model: str | None
    latitude: float | None
    longitude: float | None


class PhotoPage(BaseModel):
    items: list[PhotoSummary]
    total: int
    limit: int
    offset: int
