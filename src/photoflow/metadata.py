"""Extract a small metadata allowlist with ExifTool's read-only JSON interface."""

import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO

from photoflow.config import Settings

TAGS = (
    "FileType",
    "MIMEType",
    "ImageWidth",
    "ImageHeight",
    "Orientation",
    "DateTimeOriginal",
    "CreateDate",
    "OffsetTimeOriginal",
    "OffsetTimeDigitized",
    "Make",
    "Model",
    "GPSLatitude",
    "GPSLatitudeRef",
    "GPSLongitude",
    "GPSLongitudeRef",
)
IMAGE_TYPES = frozenset({"JPEG", "PNG", "TIFF", "WEBP"})
OFFSET_PATTERN = re.compile(r"^[+-](?:0\d|1[0-3]):[0-5]\d$|^[+-]14:00$")


class MetadataError(RuntimeError):
    """A safe error code without ExifTool output, private metadata, or paths."""


@dataclass(frozen=True)
class PhotoMetadata:
    format: str
    mime_type: str
    width: int
    height: int
    orientation: int | None = None
    captured_at: datetime | None = None
    captured_at_offset: str | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    latitude: float | None = None
    longitude: float | None = None


def _capture_time(tags: dict) -> tuple[datetime | None, str | None]:
    for date_tag, offset_tag in (
        ("DateTimeOriginal", "OffsetTimeOriginal"),
        ("CreateDate", "OffsetTimeDigitized"),
    ):
        value = tags.get(date_tag)
        if not isinstance(value, str):
            continue
        # Keep the camera's wall time; do not invent a timezone when absent.
        normalized = re.sub(r"^(\d{4}):(\d{2}):(\d{2})", r"\1-\2-\3", value)
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            continue
        offset = tags.get(offset_tag)
        if not isinstance(offset, str) or not OFFSET_PATTERN.fullmatch(offset):
            offset = parsed.strftime("%z") if parsed.utcoffset() is not None else None
            if offset:
                offset = offset[:3] + ":" + offset[3:]
        return parsed.replace(tzinfo=None), offset
    return None, None


def _coordinate(tags: dict, tag: str, bound: int) -> float | None:
    try:
        value = float(tags[tag])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or abs(value) > bound:
        return None
    reference = str(tags.get(tag + "Ref", "")).upper()
    if reference in {"S", "W"}:
        value = -abs(value)
    elif reference in {"N", "E"}:
        value = abs(value)
    return value


def _text(value: object) -> str | None:
    return value.strip()[:128] or None if isinstance(value, str) else None


def parse_metadata(tags: dict) -> PhotoMetadata:
    image_type = tags.get("FileType")
    if image_type not in IMAGE_TYPES:
        raise MetadataError("unsupported_image")
    try:
        width, height = int(tags["ImageWidth"]), int(tags["ImageHeight"])
        if width <= 0 or height <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise MetadataError("invalid_dimensions") from error
    captured_at, offset = _capture_time(tags)
    orientation = tags.get("Orientation")
    if not isinstance(orientation, int) or not 1 <= orientation <= 8:
        orientation = None
    return PhotoMetadata(
        format=image_type,
        mime_type={
            "JPEG": "image/jpeg",
            "PNG": "image/png",
            "TIFF": "image/tiff",
            "WEBP": "image/webp",
        }[image_type],
        width=width,
        height=height,
        orientation=orientation,
        captured_at=captured_at,
        captured_at_offset=offset,
        camera_make=_text(tags.get("Make")),
        camera_model=_text(tags.get("Model")),
        latitude=_coordinate(tags, "GPSLatitude", 90),
        longitude=_coordinate(tags, "GPSLongitude", 180),
    )


class ExifTool:
    def __init__(self, settings: Settings):
        executable = shutil.which(settings.exiftool_path)
        if executable is None:
            raise RuntimeError("ExifTool not found; install it or set PHOTOFLOW_EXIFTOOL_PATH")
        self.executable = executable
        self.timeout = settings.exiftool_timeout

    def extract(self, source: BinaryIO) -> PhotoMetadata:
        source.seek(0)
        try:
            result = subprocess.run(
                [self.executable, "-json", "-n", *(f"-{tag}" for tag in TAGS), "-"],
                stdin=source,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise MetadataError("metadata_timeout") from error
        except OSError as error:
            raise MetadataError("metadata_unavailable") from error
        if result.returncode != 0:
            raise MetadataError("metadata_failed")
        try:
            records = json.loads(result.stdout)
            if (
                not isinstance(records, list)
                or len(records) != 1
                or not isinstance(records[0], dict)
            ):
                raise ValueError
        except (ValueError, UnicodeDecodeError) as error:
            raise MetadataError("invalid_metadata_response") from error
        if "Error" in records[0]:
            raise MetadataError("metadata_failed")
        return parse_metadata(records[0])
