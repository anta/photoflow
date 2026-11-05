import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from photoflow.indexer import utc_now
from photoflow.main import create_app
from photoflow.models import Photo


@pytest.fixture
def client(settings, engine):
    with Session(engine) as session:
        for name, missing in (("b.jpg", False), ("a%.jpg", False), ("c.jpg", True)):
            session.add(
                Photo(
                    relative_path=name,
                    size_bytes=100,
                    mtime_ns=1,
                    ctime_ns=1,
                    width=120,
                    height=80,
                    format="JPEG",
                    mime_type="image/jpeg",
                    indexed_at=utc_now(),
                    last_seen_scan="synthetic",
                    is_missing=missing,
                    camera_make="Synthetic",
                    latitude=12.5,
                    longitude=-34.25,
                )
            )
        session.commit()
    with TestClient(create_app(settings)) as client:
        yield client


def test_paginated_photos_have_deterministic_order_and_hide_internal_fields(client):
    response = client.get("/api/v1/photos", params={"limit": 1})
    assert response.status_code == 200
    page = response.json()
    assert (page["total"], page["limit"], page["offset"]) == (2, 1, 0)
    assert page["items"][0]["relative_path"] == "a%.jpg"
    assert "mtime_ns" not in page["items"][0]
    assert "latitude" not in page["items"][0]
    assert page["items"][0]["indexed_at"].endswith("+00:00")
    assert response.headers["cache-control"] == "private, no-store"
    next_page = client.get("/api/v1/photos?limit=1&offset=1").json()
    assert next_page["items"][0]["relative_path"] == "b.jpg"
    assert client.get("/api/v1/photos?offset=100").json()["items"] == []


def test_search_escapes_sql_wildcards_and_missing_is_opt_in(client):
    assert client.get("/api/v1/photos?query=%25").json()["total"] == 1
    assert client.get("/api/v1/photos?include_missing=true").json()["total"] == 3
    assert client.get("/api/v1/photos?query=absent").json()["total"] == 0


def test_details_include_allowlisted_metadata(client):
    photo_id = client.get("/api/v1/photos").json()["items"][0]["id"]
    photo = client.get(f"/api/v1/photos/{photo_id}").json()
    assert photo["camera_make"] == "Synthetic"
    assert photo["latitude"] == 12.5
    assert "root_fingerprint" not in photo
    assert "last_seen_scan" not in photo
    assert client.get("/api/v1/photos/999999").status_code == 404


@pytest.mark.parametrize("suffix", ["?limit=0", "?limit=201", "?offset=-1", "/0", "/abc"])
def test_invalid_parameters(client, suffix):
    assert client.get("/api/v1/photos" + suffix).status_code == 422


def test_no_photo_mutation_api(client):
    assert client.post("/api/v1/photos").status_code == 405
    assert client.delete("/api/v1/photos/1").status_code == 405


def test_database_failures_do_not_leak_paths_or_query_parameters(client):
    from unittest.mock import patch

    from sqlalchemy.exc import SQLAlchemyError

    with patch.object(Session, "scalar", side_effect=SQLAlchemyError("private absolute path")):
        response = client.get("/api/v1/photos")
    assert response.status_code == 503
    assert response.json() == {"detail": "Photo index unavailable"}
