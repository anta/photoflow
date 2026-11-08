"""Virtual date albums derived from the current index, without stored memberships."""

import re
from collections import Counter
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from photoflow.models import Photo
from photoflow.schemas import AlbumSummary


def eligible_photos() -> list[ColumnElement[bool]]:
    return [Photo.is_missing.is_(False), Photo.index_error.is_(None)]


def list_albums(session: Session) -> list[AlbumSummary]:
    # SQLite stores ISO camera wall times. Slice rather than round fractional seconds
    # through date functions, which could move a late capture into the next month.
    month = func.substr(Photo.captured_at, 1, 7)
    groups = session.execute(
        select(month, func.count()).where(*eligible_photos()).group_by(month)
    ).all()
    years: Counter[str] = Counter()
    months = {}
    undated = 0
    for date, count in groups:
        if date is None:
            undated = count
        else:
            months[date] = count
            years[date[:4]] += count

    albums = [AlbumSummary(id="all", label="All photos", photo_count=sum(years.values()) + undated)]
    for year in sorted(years, reverse=True):
        albums.append(AlbumSummary(id=f"year-{year}", label=year, photo_count=years[year]))
        for date in sorted((date for date in months if date[:4] == year), reverse=True):
            albums.append(AlbumSummary(id=f"month-{date}", label=date, photo_count=months[date]))
    albums.append(AlbumSummary(id="undated", label="Undated", photo_count=undated))
    return albums


def album_filters(album_id: str) -> list[ColumnElement[bool]]:
    """Resolve a rule ID to indexed date bounds, or raise ValueError for invalid IDs."""
    filters = eligible_photos()
    if album_id == "all":
        return filters
    if album_id == "undated":
        return [*filters, Photo.captured_at.is_(None)]

    match = re.fullmatch(r"(year|month)-([0-9]{4})(?:-([0-9]{2}))?", album_id)
    if match is None:
        raise ValueError("Invalid album ID")
    kind, year, month = match.groups()
    if (kind == "month") != (month is not None):
        raise ValueError("Invalid album ID")
    start = datetime(int(year), int(month or 1), 1)
    if kind == "year" or start.month == 12:
        end = datetime(start.year + 1, 1, 1) if start.year < 9999 else None
    else:
        end = datetime(start.year, start.month + 1, 1)
    filters.append(Photo.captured_at >= start)
    if end is not None:
        filters.append(Photo.captured_at < end)
    return filters
