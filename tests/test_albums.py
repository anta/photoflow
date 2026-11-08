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


def test_album_database_errors_are_private_and_unsupported_mutations_are_rejected(client):
    for path, method in (("/api/v1/albums", "execute"), ("/api/v1/albums/all/photos", "scalar")):
        with patch.object(Session, method, side_effect=SQLAlchemyError("private path")):
            response = client.get(path)
        assert response.status_code == 503
        assert response.json() == {"detail": "Photo index unavailable"}
        assert client.post(path).status_code == (422 if path == "/api/v1/albums" else 405)
        assert client.delete(path).status_code == 405


def create_album(client, name="Winter", start="2024-01-01", end="2024-02-29"):
    response = client.post(
        "/api/v1/albums",
        json={
            "name": name,
            "rule": {"version": 1, "type": "date_range", "start_date": start, "end_date": end},
        },
    )
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "private, no-store"
    return response.json()


def test_saved_albums_overlap_and_include_complete_calendar_days(client, dated_library):
    winter = create_album(client, name="  Winter  ")
    assert winter == {
        "id": "saved-1",
        "label": "Winter",
        "photo_count": 4,
        "rule": {
            "version": 1,
            "type": "date_range",
            "start_date": "2024-01-01",
            "end_date": "2024-02-29",
        },
    }
    # This includes both unknown offsets and a +14:00 capture still in the previous UTC year.
    january = create_album(client, name="January", end="2024-01-31")
    assert january["photo_count"] == 2
    same_day = create_album(client, name="Leap day", start="2024-02-29", end="2024-02-29")
    assert same_day["photo_count"] == 1
    day_items = client.get(f"/api/v1/albums/{same_day['id']}/photos").json()["items"]
    assert day_items[0]["relative_path"] == "e-leap-day.jpg"

    ids = {}
    for album in (winter, january, same_day):
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
        assert [item["relative_path"] for item in items] == sorted(
            item["relative_path"] for item in items
        )
        ids[album["id"]] = {item["id"] for item in items}
        assert len(ids[album["id"]]) == album["photo_count"]
    assert ids[january["id"]] < ids[winter["id"]]
    assert ids[same_day["id"]] < ids[winter["id"]]
    assert client.get("/api/v1/albums").json()[-3:] == [winter, january, same_day]


def test_saved_empty_albums_and_rules_survive_app_restart(settings, engine):
    with TestClient(create_app(settings)) as client:
        album = create_album(client, name="Fictional holiday 🌞")
        assert album["photo_count"] == 0
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get("/api/v1/albums").json()[-1] == album
        response = restarted.get(f"/api/v1/albums/{album['id']}/photos?limit=2&offset=4")
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "limit": 2, "offset": 4}
        # Names are display labels, not IDs or SQL expressions; duplicates are allowed.
        second = create_album(restarted, name="Fictional holiday 🌞")
        assert second["id"] != album["id"]


def test_saved_albums_exclude_missing_errors_and_undated(client, dated_library):
    album = create_album(client, start="2023-01-01", end="2027-12-31")
    assert album["photo_count"] == 6
    items = client.get(f"/api/v1/albums/{album['id']}/photos").json()["items"]
    assert len(items) == 6
    assert all(item["captured_at"] is not None for item in items)
    assert all(not item["is_missing"] and item["index_error"] is None for item in items)
    assert all("mtime_ns" not in item and "latitude" not in item for item in items)
    empty = create_album(client, name="Only unavailable", start="2025-01-01", end="2027-12-31")
    assert empty["photo_count"] == 0
    assert client.get(f"/api/v1/albums/{empty['id']}/photos").status_code == 200


def test_saved_date_range_handles_first_and_last_supported_calendar_days(client, engine):
    with Session(engine) as session:
        add_photo(session, "first.jpg", datetime.min)
        add_photo(session, "last.jpg", datetime.max)
        session.commit()
    for start, end, total in (
        ("0001-01-01", "0001-01-01", 1),
        ("9999-12-31", "9999-12-31", 1),
        ("0001-01-01", "9999-12-31", 2),
    ):
        album = create_album(client, start=start, end=end)
        assert album["photo_count"] == total
        page = client.get(f"/api/v1/albums/{album['id']}/photos").json()
        assert len(page["items"]) == page["total"] == total


@pytest.mark.parametrize(
    "changes",
    [
        {"name": ""},
        {"name": " \t\n "},
        {"name": "x" * 129},
        {"name": None},
        {"name": 123},
        {"sql": "SELECT * FROM photos"},
        {"rule": None},
        {"rule": {}},
        {"rule": {"version": 2}},
        {"rule": {"version": True}},
        {"rule": {"version": "1"}},
        {"rule": {"type": "sql"}},
        {"rule": {"start_date": "2024-03-01"}},
        {"rule": {"start_date": "2024-1-01"}},
        {"rule": {"start_date": "2023-02-29"}},
        {"rule": {"end_date": "2024-02-30"}},
        {"rule": {"start_date": "0000-01-01"}},
        {"rule": {"end_date": "10000-01-01"}},
        {"rule": {"start_date": "2024-01-01T00:00:00"}},
        {"rule": {"end_date": 1709164800}},
        {"rule": {"end_date": None}},
        {"rule": {"query": "arbitrary SQL"}},
    ],
)
def test_invalid_saved_album_definitions_are_rejected_without_persistence(client, changes):
    definition = {
        "name": "Synthetic album",
        "rule": {
            "version": 1,
            "type": "date_range",
            "start_date": "2024-01-01",
            "end_date": "2024-02-29",
        },
    }
    if isinstance(changes.get("rule"), dict):
        definition["rule"].update(changes["rule"])
        if changes["rule"] == {}:
            definition["rule"] = {}
    else:
        definition.update(changes)
    assert client.post("/api/v1/albums", json=definition).status_code == 422
    assert [album["id"] for album in client.get("/api/v1/albums").json()] == ["all", "undated"]


@pytest.mark.parametrize(
    "album_id",
    ["saved-0", "saved-01", "saved-no", "saved-999", "saved-" + "9" * 19, "saved-" + "1" * 50],
)
def test_invalid_or_unknown_saved_album_ids_return_404(client, album_id):
    response = client.get(f"/api/v1/albums/{album_id}/photos")
    assert response.status_code == 404
    assert response.json() == {"detail": "Album not found"}


def test_failed_album_write_returns_private_error_and_does_not_persist(client):
    with patch.object(Session, "commit", side_effect=SQLAlchemyError("private path")):
        response = client.post(
            "/api/v1/albums",
            json={
                "name": "Synthetic",
                "rule": {
                    "version": 1,
                    "type": "date_range",
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                },
            },
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "Photo index unavailable"}
    assert len(client.get("/api/v1/albums").json()) == 2
