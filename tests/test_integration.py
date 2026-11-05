"""Integration data is generated at runtime; no real photographs are used."""

import hashlib
import io
import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from photoflow.indexer import index_library
from photoflow.main import create_app
from photoflow.metadata import ExifTool, MetadataError
from photoflow.models import Photo
from photoflow.thumbnails import ThumbnailError, ThumbnailService

pytestmark = pytest.mark.integration


def snapshot(root):
    return {
        path.relative_to(root).as_posix(): (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
            path.stat().st_mode,
        )
        for path in root.rglob("*")
        if path.is_file()
    }


def test_all_supported_formats_on_read_only_nas_stay_unchanged(settings, engine):
    paths = []
    for extension, format_name in (
        ("JPG", "JPEG"),
        ("jpeg", "JPEG"),
        ("png", "PNG"),
        ("tif", "TIFF"),
        ("tiff", "TIFF"),
        ("webp", "WEBP"),
    ):
        photo = settings.nas_root / f"nested/æ-synthetic.{extension}"
        photo.parent.mkdir(exist_ok=True)
        Image.new("RGB", (96, 64), "blue").save(photo, format=format_name)
        photo.chmod(0o444)
        paths.append(photo)
    nested = settings.nas_root / "nested"
    nested.chmod(0o555)
    settings.nas_root.chmod(0o555)
    before = snapshot(settings.nas_root)
    try:
        result = index_library(settings)
        assert (result.added, result.failed) == (6, 0)
        with TestClient(create_app(settings)) as client:
            page = client.get("/api/v1/photos").json()
            assert page["total"] == 6
            for item in page["items"]:
                response = client.get(item["thumbnail_url"])
                assert response.status_code == 200
                with Image.open(io.BytesIO(response.content)) as thumb:
                    assert thumb.size == (96, 64)
                    assert not thumb.getexif()
            assert client.get("/api/v1/photos?limit=2&offset=4").json()["total"] == 6
        with patch("photoflow.indexer.ExifTool.extract", side_effect=AssertionError("must skip")):
            assert index_library(settings).unchanged == 6
        assert snapshot(settings.nas_root) == before
        assert set(snapshot(settings.nas_root)) == {
            p.relative_to(settings.nas_root).as_posix() for p in paths
        }
    finally:
        settings.nas_root.chmod(0o755)
        nested.chmod(0o755)
        for photo in paths:
            photo.chmod(0o644)


def test_synthetic_gps_and_offsets_roundtrip_without_thumbnail_metadata(settings, engine):
    photo = settings.nas_root / "synthetic-metadata.jpg"
    exif = Image.Exif()
    exif[36867] = "2024:02:03 10:11:12"
    exif[36881] = "+02:00"
    exif[271] = "Synthetic"
    exif[34853] = {1: "S", 2: (12.0, 30.0, 0.0), 3: "W", 4: (34.0, 15.0, 0.0)}
    Image.new("RGB", (120, 80), "green").save(photo, exif=exif)
    before = snapshot(settings.nas_root)
    assert index_library(settings).added == 1
    with TestClient(create_app(settings)) as client:
        item = client.get("/api/v1/photos").json()["items"][0]
        detail = client.get(f"/api/v1/photos/{item['id']}").json()
        assert detail["captured_at"] == "2024-02-03T10:11:12"
        assert detail["captured_at_offset"] == "+02:00"
        assert (detail["latitude"], detail["longitude"]) == (-12.5, -34.25)
        with Image.open(io.BytesIO(client.get(item["thumbnail_url"]).content)) as thumb:
            assert not thumb.getexif()
    assert snapshot(settings.nas_root) == before


def test_failed_reindex_is_retried_even_without_stat_changes(settings, engine):
    Image.new("RGB", (100, 60)).save(settings.nas_root / "generated.jpg")
    index_library(settings)
    with patch("photoflow.indexer.ExifTool.extract", side_effect=MetadataError("metadata_timeout")):
        assert index_library(settings, force=True).failed == 1
    with Session(engine) as session:
        photo = session.scalar(select(Photo))
        assert photo.index_error == "metadata_timeout"
        with pytest.raises(ThumbnailError) as error:
            ThumbnailService(settings).get(photo)
        assert error.value.status_code == 409
    assert index_library(settings).updated == 1
    with Session(engine) as session:
        assert session.scalar(select(Photo)).index_error is None


def test_file_changed_during_extraction_is_not_indexed(settings, engine):
    path = settings.nas_root / "generated.jpg"
    Image.new("RGB", (100, 60)).save(path)
    extract = ExifTool(settings).extract

    def change_during_read(_self, source):
        metadata = extract(source)
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        return metadata

    with patch("photoflow.indexer.ExifTool.extract", new=change_during_read):
        result = index_library(settings)
    assert (result.added, result.failed) == (0, 1)
    with Session(engine) as session:
        assert session.scalar(select(Photo)) is None


def test_cli_runs_from_outside_repository_with_packaged_migrations(settings, tmp_path):
    Image.new("RGB", (100, 60)).save(settings.nas_root / "generated.jpg")
    env = {key: value for key, value in os.environ.items() if not key.startswith("PHOTOFLOW_")}
    env.update(PHOTOFLOW_NAS_ROOT=str(settings.nas_root), PHOTOFLOW_DATA_DIR=str(settings.data_dir))
    for command in ("migrate", "index", "index"):
        result = subprocess.run(
            [sys.executable, "-m", "photoflow", command],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
    assert json.loads(result.stdout)["unchanged"] == 1
