from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from photoflow.indexer import utc_now
from photoflow.main import create_app
from photoflow.models import Photo


@pytest.fixture
def client(settings, engine):
    with TestClient(create_app(settings)) as client:
        yield client


def add_photo(session, name, captured_at=None, **changes):
    photo = Photo(
        relative_path=name,
        size_bytes=100,
        mtime_ns=1,
        ctime_ns=1,
        indexed_at=utc_now(),
        last_seen_scan="synthetic",
        captured_at=captured_at,
        **changes,
    )
    session.add(photo)


@pytest.fixture
def dated_library(engine):
    with Session(engine) as session:
        for name, date, offset in (
            ("a-year-end.jpg", datetime(2023, 12, 31, 23, 59, 59, 999999), "-12:00"),
            ("b-new-year.jpg", datetime(2024, 1, 1), "+14:00"),
            ("c-january.jpg", datetime(2024, 1, 31, 23, 59, 59, 999999), None),
            ("d-february.jpg", datetime(2024, 2, 1), "-03:00"),
            ("e-leap-day.jpg", datetime(2024, 2, 29, 23, 59, 59, 999999), None),
            ("f-march.jpg", datetime(2024, 3, 1), None),
            ("g-undated.jpg", None, None),
        ):
            add_photo(session, name, date, captured_at_offset=offset)
        add_photo(session, "missing.jpg", datetime(2025, 1, 1), is_missing=True)
        add_photo(session, "error.jpg", datetime(2026, 1, 1), index_error="metadata_failed")
        add_photo(
            session,
            "missing-error.jpg",
            datetime(2027, 1, 1),
            is_missing=True,
            index_error="metadata_failed",
        )
        add_photo(session, "missing-undated.jpg", is_missing=True)
        add_photo(session, "error-undated.jpg", index_error="metadata_failed")
        session.commit()


def test_empty_library_has_all_and_undated_albums(client):
    assert client.get("/api/v1/albums").json() == [
        {"id": "all", "label": "All photos", "photo_count": 0},
        {"id": "undated", "label": "Undated", "photo_count": 0},
    ]
    for album_id in ("all", "undated"):
        response = client.get(f"/api/v1/albums/{album_id}/photos?limit=2&offset=4")
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "limit": 2, "offset": 4}


def test_album_counts_order_and_wall_time_boundaries(client, dated_library):
    response = client.get("/api/v1/albums")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json() == [
        {"id": "all", "label": "All photos", "photo_count": 7},
        {"id": "year-2024", "label": "2024", "photo_count": 5},
        {"id": "month-2024-03", "label": "2024-03", "photo_count": 1},
        {"id": "month-2024-02", "label": "2024-02", "photo_count": 2},
        {"id": "month-2024-01", "label": "2024-01", "photo_count": 2},
        {"id": "year-2023", "label": "2023", "photo_count": 1},
        {"id": "month-2023-12", "label": "2023-12", "photo_count": 1},
        {"id": "undated", "label": "Undated", "photo_count": 1},
    ]
    january = client.get("/api/v1/albums/month-2024-01/photos").json()["items"]
    assert [item["relative_path"] for item in january] == ["b-new-year.jpg", "c-january.jpg"]
    assert [item["captured_at_offset"] for item in january] == ["+14:00", None]
    december = client.get("/api/v1/albums/month-2023-12/photos").json()["items"]
    assert december[0]["relative_path"] == "a-year-end.jpg"
    assert december[0]["captured_at_offset"] == "-12:00"


def test_each_album_paginates_with_matching_totals_and_overlapping_membership(
    client, dated_library
):
    contents = {}
    for album in client.get("/api/v1/albums").json():
        items = []
        for offset in range(album["photo_count"] + 1):
            response = client.get(
                f"/api/v1/albums/{album['id']}/photos", params={"limit": 1, "offset": offset}
            )
            assert response.status_code == 200
            page = response.json()
            assert (page["total"], page["limit"], page["offset"]) == (
                album["photo_count"],
                1,
                offset,
            )
            items.extend(page["items"])
        assert len(items) == len({item["id"] for item in items}) == album["photo_count"]
        assert [item["relative_path"] for item in items] == sorted(
            item["relative_path"] for item in items
        )
        assert all(not item["is_missing"] and item["index_error"] is None for item in items)
        assert all("mtime_ns" not in item and "latitude" not in item for item in items)
        contents[album["id"]] = {item["id"] for item in items}
    assert contents["month-2024-01"] < contents["year-2024"] < contents["all"]
    assert contents["undated"].isdisjoint(contents["year-2024"] | contents["year-2023"])
    # Existing photo browsing still exposes retained error records for diagnosis.
    assert client.get("/api/v1/photos").json()["total"] == 9


def test_supported_calendar_extremes(client, engine):
    with Session(engine) as session:
        add_photo(session, "first.jpg", datetime.min)
        add_photo(session, "last.jpg", datetime.max)
        session.commit()
    counts = {album["id"]: album["photo_count"] for album in client.get("/api/v1/albums").json()}
    assert counts == {
        "all": 2,
        "year-9999": 1,
        "month-9999-12": 1,
        "year-0001": 1,
        "month-0001-01": 1,
        "undated": 0,
    }
    for album_id in ("year-0001", "month-0001-01", "year-9999", "month-9999-12"):
        response = client.get(f"/api/v1/albums/{album_id}/photos")
        assert response.status_code == 200
        assert len(response.json()["items"]) == response.json()["total"] == 1


@pytest.mark.parametrize(
    "album_id",
    [
        "unknown",
        "year-0000",
        "year-10000",
        "year-2024-01",
        "month-2024",
        "month-2024-00",
        "month-2024-13",
        "month-2024-1",
        "month-2024-01-extra",
        "year-2022",
        "month-2024-04",
        "year-2025",
        "year-2026",
    ],
)
def test_invalid_or_empty_date_albums_return_404(client, dated_library, album_id):
    response = client.get(f"/api/v1/albums/{album_id}/photos")
    assert response.status_code == 404
    assert response.json() == {"detail": "Album not found"}


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1", "limit=abc"])
def test_album_pagination_validation(client, query):
    assert client.get(f"/api/v1/albums/all/photos?{query}").status_code == 422


def test_album_database_errors_are_private_and_routes_are_read_only(client):
    for path, method in (("/api/v1/albums", "execute"), ("/api/v1/albums/all/photos", "scalar")):
        with patch.object(Session, method, side_effect=SQLAlchemyError("private path")):
            response = client.get(path)
        assert response.status_code == 503
        assert response.json() == {"detail": "Photo index unavailable"}
        assert client.post(path).status_code == 405
        assert client.delete(path).status_code == 405
