"""Public API fields; internal fingerprints and filesystem timestamps stay private."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, computed_field, field_serializer


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

    @computed_field
    @property
    def thumbnail_url(self) -> str | None:
        if self.is_missing or self.index_error is not None:
            return None
        return f"/api/v1/photos/{self.id}/thumbnail"


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


class AlbumSummary(BaseModel):
    id: str
    label: str
    photo_count: int
