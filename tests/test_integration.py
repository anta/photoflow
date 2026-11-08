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


def write_dated_photo(path, date=None, offset=None):
    exif = Image.Exif()
    if date is not None:
        exif[36867] = date
    if offset is not None:
        exif[36881] = offset
    if path.exists():
        path.chmod(0o644)
    Image.new("RGB", (96, 64), "blue").save(path, exif=exif)
    path.chmod(0o444)


def album_counts(client):
    response = client.get("/api/v1/albums")
    assert response.status_code == 200
    albums = response.json()
    for album in albums:
        page = client.get(f"/api/v1/albums/{album['id']}/photos").json()
        assert len(page["items"]) == page["total"] == album["photo_count"]
    return {album["id"]: album["photo_count"] for album in albums}


def test_date_albums_from_real_exif_leave_read_only_originals_unchanged(settings, engine):
    for name, date, offset in (
        ("year-end.jpg", "2023:12:31 23:59:59", "-12:00"),
        ("new-year.jpg", "2024:01:01 00:00:00", "+14:00"),
        ("unknown-offset.jpg", "2024:01:15 12:00:00", None),
        ("invalid-date.jpg", "0000:00:00 00:00:00", None),
        ("no-date.jpg", None, None),
    ):
        write_dated_photo(settings.nas_root / name, date, offset)
    settings.nas_root.chmod(0o555)
    before = snapshot(settings.nas_root)
    try:
        assert index_library(settings).added == 5
        with TestClient(create_app(settings)) as client:
            assert album_counts(client) == {
                "all": 5,
                "year-2024": 2,
                "month-2024-01": 2,
                "year-2023": 1,
                "month-2023-12": 1,
                "undated": 2,
            }
            january = client.get("/api/v1/albums/month-2024-01/photos").json()["items"]
            assert [item["captured_at_offset"] for item in january] == ["+14:00", None]
            for item in january:
                assert client.get(item["thumbnail_url"]).status_code == 200
        assert index_library(settings).unchanged == 5
        assert snapshot(settings.nas_root) == before
    finally:
        settings.nas_root.chmod(0o755)
        for path in settings.nas_root.iterdir():
            path.chmod(0o644)


def test_albums_follow_incremental_updates_missing_restore_and_retries(settings, engine):
    path = settings.nas_root / "changing.jpg"
    write_dated_photo(path, "2024:01:15 12:00:00")

    def index_unchanged_sources(**kwargs):
        before = snapshot(settings.nas_root)
        result = index_library(settings, **kwargs)
        assert snapshot(settings.nas_root) == before
        return result

    assert index_unchanged_sources().added == 1
    with TestClient(create_app(settings)) as client:
        assert album_counts(client) == {
            "all": 1,
            "year-2024": 1,
            "month-2024-01": 1,
            "undated": 0,
        }
        photo_id = client.get("/api/v1/albums/all/photos").json()["items"][0]["id"]

        write_dated_photo(path, "2025:02:15 12:00:00")
        assert index_unchanged_sources().updated == 1
        assert album_counts(client) == {
            "all": 1,
            "year-2025": 1,
            "month-2025-02": 1,
            "undated": 0,
        }
        assert client.get("/api/v1/albums/year-2024/photos").status_code == 404

        # Clearing capture metadata moves the same record to Undated, without mtime fallback.
        write_dated_photo(path)
        assert index_unchanged_sources().updated == 1
        assert album_counts(client) == {"all": 1, "undated": 1}
        write_dated_photo(settings.nas_root / "new.jpg", "2026:03:15 12:00:00")
        assert index_unchanged_sources().added == 1
        assert album_counts(client) == {
            "all": 2,
            "year-2026": 1,
            "month-2026-03": 1,
            "undated": 1,
        }

        parked = settings.nas_root / "parked.txt"
        path.rename(parked)
        assert index_unchanged_sources().missing == 1
        assert album_counts(client)["undated"] == 0
        assert album_counts(client)["all"] == 1
        parked.rename(path)
        assert index_unchanged_sources().updated == 1
        assert album_counts(client)["undated"] == 1
        assert client.get("/api/v1/albums/undated/photos").json()["items"][0]["id"] == photo_id

        # Failed updates retain old metadata but remove records from every generated album.
        with patch(
            "photoflow.indexer.ExifTool.extract", side_effect=MetadataError("metadata_failed")
        ):
            assert index_unchanged_sources(force=True).failed == 2
        assert album_counts(client) == {"all": 0, "undated": 0}
        assert client.get("/api/v1/photos").json()["total"] == 2
        assert index_unchanged_sources().updated == 2
        assert album_counts(client) == {
            "all": 2,
            "year-2026": 1,
            "month-2026-03": 1,
            "undated": 1,
        }


def test_saved_rules_survive_reindexing_and_follow_current_membership(settings, engine):
    path = settings.nas_root / "changing.jpg"
    write_dated_photo(path, "2024:02:29 23:59:59", "+14:00")
    write_dated_photo(settings.nas_root / "undated.jpg")

    def scan(**kwargs):
        before = snapshot(settings.nas_root)
        result = index_library(settings, **kwargs)
        assert snapshot(settings.nas_root) == before
        return result

    assert scan().added == 2
    with TestClient(create_app(settings)) as client:
        saved = []
        for name, start, end in (
            ("Leap day", "2024-02-29", "2024-02-29"),
            ("The whole year", "2024-01-01", "2024-12-31"),
        ):
            before = snapshot(settings.nas_root)
            response = client.post(
                "/api/v1/albums",
                json={
                    "name": name,
                    "rule": {
                        "version": 1,
                        "type": "date_range",
                        "start_date": start,
                        "end_date": end,
                    },
                },
            )
            assert response.status_code == 201
            saved.append(response.json())
            assert snapshot(settings.nas_root) == before

        def check_counts(*counts):
            before = snapshot(settings.nas_root)
            summaries = {album["id"]: album for album in client.get("/api/v1/albums").json()}
            for album, count in zip(saved, counts, strict=True):
                assert summaries[album["id"]] == album | {"photo_count": count}
                response = client.get(f"/api/v1/albums/{album['id']}/photos")
                assert response.status_code == 200
                page = response.json()
                assert len(page["items"]) == page["total"] == count
            assert snapshot(settings.nas_root) == before

        check_counts(1, 1)
        first_id = client.get(f"/api/v1/albums/{saved[0]['id']}/photos").json()["items"][0]["id"]
        write_dated_photo(path, "2024:03:01 00:00:00")
        assert scan().updated == 1
        check_counts(0, 1)
        write_dated_photo(path)
        assert scan().updated == 1
        check_counts(0, 0)
        write_dated_photo(path, "2024:02:29 12:00:00")
        assert scan().updated == 1
        check_counts(1, 1)
        with patch(
            "photoflow.indexer.ExifTool.extract", side_effect=MetadataError("metadata_failed")
        ):
            assert scan(force=True).failed == 2
        check_counts(0, 0)
        assert scan().updated == 2
        check_counts(1, 1)
        parked = settings.nas_root / "parked.txt"
        path.rename(parked)
        assert scan().missing == 1
        check_counts(0, 0)
        parked.rename(path)
        assert scan().updated == 1
        check_counts(1, 1)
        restored_id = client.get(f"/api/v1/albums/{saved[0]['id']}/photos").json()["items"][0]["id"]
        assert restored_id == first_id
        write_dated_photo(settings.nas_root / "new.jpg", "2024:02:29 12:00:00")
        assert scan().added == 1
        check_counts(2, 2)


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
