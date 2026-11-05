import subprocess
from datetime import datetime
from unittest.mock import patch

import pytest
from PIL import Image

from photoflow.metadata import ExifTool, MetadataError, parse_metadata
from photoflow.nas import NasRoot


def tags(**extra):
    return {"FileType": "JPEG", "ImageWidth": 120, "ImageHeight": 80} | extra


def test_dates_offsets_gps_and_allowlist():
    result = parse_metadata(
        tags(
            DateTimeOriginal="2024:02:03 10:11:12",
            OffsetTimeOriginal="+02:00",
            GPSLatitude=12.5,
            GPSLatitudeRef="S",
            GPSLongitude=34.25,
            GPSLongitudeRef="W",
            Make=" Synthetic ",
            Model="Test camera",
            SerialNumber="DO NOT RETAIN",
        )
    )
    assert result.captured_at == datetime(2024, 2, 3, 10, 11, 12)
    assert result.captured_at_offset == "+02:00"
    assert (result.latitude, result.longitude) == (-12.5, -34.25)
    assert result.camera_make == "Synthetic"
    assert not hasattr(result, "serial_number")


def test_invalid_optional_metadata_is_nullable():
    result = parse_metadata(
        tags(
            DateTimeOriginal="0000:00:00 00:00:00",
            GPSLatitude="NaN",
            GPSLongitude=200,
            Orientation=99,
            Make=123,
        )
    )
    assert result.captured_at is None
    assert result.captured_at_offset is None
    assert result.latitude is result.longitude is result.orientation is result.camera_make is None


def test_create_date_fallback_does_not_invent_timezone():
    result = parse_metadata(tags(DateTimeOriginal="bad", CreateDate="2024:01:02 03:04:05"))
    assert result.captured_at == datetime(2024, 1, 2, 3, 4, 5)
    assert result.captured_at_offset is None


@pytest.mark.parametrize("value", ["+00:00", "-05:30", "+14:00"])
def test_valid_offsets(value):
    assert (
        parse_metadata(
            tags(DateTimeOriginal="2024:01:02 03:04:05", OffsetTimeOriginal=value)
        ).captured_at_offset
        == value
    )


@pytest.mark.parametrize("value", ["+24:00", "UTC", "+14:59"])
def test_invalid_offsets_are_not_stored(value):
    assert (
        parse_metadata(
            tags(DateTimeOriginal="2024:01:02 03:04:05", OffsetTimeOriginal=value)
        ).captured_at_offset
        is None
    )


@pytest.mark.parametrize("values", [tags(FileType="TXT"), tags(ImageWidth=0)])
def test_nonphotos_and_bad_dimensions_fail(values):
    with pytest.raises(MetadataError):
        parse_metadata(values)


@pytest.mark.integration
def test_real_exiftool_reads_synthetic_exif_without_touching_original(settings):
    photo = settings.nas_root / "generated.jpg"
    exif = Image.Exif()
    exif[36867] = "2024:02:03 10:11:12"
    exif[271] = "Synthetic"
    exif[272] = "Test camera"
    exif[274] = 6
    Image.new("RGB", (120, 80), "red").save(photo, exif=exif)
    before = photo.read_bytes(), photo.stat().st_mtime_ns
    with NasRoot(settings.nas_root).open_photo("generated.jpg") as source:
        metadata = ExifTool(settings).extract(source)
    assert metadata.width == 120 and metadata.height == 80
    assert metadata.captured_at == datetime(2024, 2, 3, 10, 11, 12)
    assert metadata.camera_make == "Synthetic"
    assert metadata.orientation == 6
    assert (photo.read_bytes(), photo.stat().st_mtime_ns) == before


def test_missing_exiftool_has_actionable_error(settings):
    with pytest.raises(RuntimeError, match="ExifTool not found"):
        ExifTool(settings.model_copy(update={"exiftool_path": "photoflow-nonexistent-tool"}))


def test_timeout_and_invalid_response_are_safe_errors(settings):
    photo = settings.nas_root / "synthetic.jpg"
    photo.write_bytes(b"synthetic")
    tool = ExifTool(settings)
    for response, code in [
        (subprocess.TimeoutExpired("exiftool", 30), "metadata_timeout"),
        (subprocess.CompletedProcess([], 0, b"garbage", b"private"), "invalid_metadata_response"),
        (subprocess.CompletedProcess([], 1, b"", b"private"), "metadata_failed"),
    ]:
        arguments = (
            {"side_effect": response}
            if isinstance(response, Exception)
            else {"return_value": response}
        )
        with (
            photo.open("rb") as source,
            patch("photoflow.metadata.subprocess.run", **arguments),
            pytest.raises(MetadataError, match=f"^{code}$"),
        ):
            tool.extract(source)
