import io
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from photoflow.indexer import index_library
from photoflow.main import create_app
from photoflow.models import Photo
from photoflow.thumbnails import ThumbnailError, ThumbnailService


@pytest.mark.integration
def test_thumbnail_orientation_cache_privacy_and_source_preservation(settings, engine):
    path = settings.nas_root / "generated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    exif[271] = "Synthetic camera data"
    exif[36867] = "2024:01:02 03:04:05"
    Image.new("RGB", (800, 400), "red").save(path, exif=exif)
    before = path.read_bytes(), path.stat().st_mtime_ns
    index_library(settings)
    with Session(engine) as session:
        photo = session.scalar(select(Photo))
        service = ThumbnailService(settings)
        content = service.get(photo)
        with Image.open(io.BytesIO(content)) as thumbnail:
            assert thumbnail.size == (200, 400)
            assert thumbnail.mode == "RGB" and thumbnail.format == "JPEG"
            assert not thumbnail.getexif()
            assert "icc_profile" not in thumbnail.info
        assert service.cache_path(photo).is_relative_to(settings.data_dir)
        with patch.object(service, "_render", side_effect=AssertionError("must use cache")):
            assert service.get(photo) == content
        changed_settings = settings.model_copy(update={"thumbnail_size": 200})
        assert ThumbnailService(changed_settings).cache_path(photo) != service.cache_path(photo)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.integration
def test_thumbnail_endpoint_and_stale_cache(settings, engine):
    path = settings.nas_root / "generated.png"
    Image.new("RGBA", (60, 30), (0, 0, 0, 0)).save(path)
    index_library(settings)
    with TestClient(create_app(settings)) as client:
        item = client.get("/api/v1/photos").json()["items"][0]
        response = client.get(item["thumbnail_url"])
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        with Image.open(io.BytesIO(response.content)) as image:
            assert image.size == (60, 30)
            assert image.getpixel((0, 0)) == (255, 255, 255)
        Image.new("RGB", (120, 80)).save(path)
        assert client.get(item["thumbnail_url"]).status_code == 409
        index_library(settings)
        assert client.get(item["thumbnail_url"]).status_code == 200
        path.unlink()
        assert client.get(item["thumbnail_url"]).status_code == 404


@pytest.mark.integration
def test_symlink_replacement_cannot_leak_external_file(settings, engine, tmp_path):
    path = settings.nas_root / "generated.jpg"
    Image.new("RGB", (120, 80)).save(path)
    index_library(settings)
    outside = tmp_path / "private.jpg"
    Image.new("RGB", (120, 80), "red").save(outside)
    path.unlink()
    path.symlink_to(outside)
    with Session(engine) as session, pytest.raises(ThumbnailError):
        ThumbnailService(settings).get(session.scalar(select(Photo)))


def test_decompression_bombs_are_rejected(settings):
    service = ThumbnailService(settings)
    source = io.BytesIO()
    Image.new("RGB", (20, 20)).save(source, "PNG")
    source.seek(0)
    with patch.object(Image, "MAX_IMAGE_PIXELS", 100), pytest.raises(ThumbnailError) as error:
        service._render(source)
    assert error.value.status_code == 413
