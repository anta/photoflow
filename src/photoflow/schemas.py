"""Public API fields; internal fingerprints and filesystem timestamps stay private."""

import re
from datetime import UTC, date, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    computed_field,
    field_serializer,
    field_validator,
    model_validator,
)


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


class DateRangeRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    type: Literal["date_range"]
    start_date: date
    end_date: date

    @field_validator("version", mode="before")
    @classmethod
    def validate_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported rule version")
        return value

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def validate_calendar_date(cls, value):
        if type(value) is date:
            return value
        if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            raise ValueError("Use a calendar date in YYYY-MM-DD format")
        return value

    @model_validator(mode="after")
    def validate_date_order(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class AlbumCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    rule: DateRangeRule


class AlbumSummary(BaseModel):
    id: str
    label: str
    photo_count: int
    rule: DateRangeRule | None = None
