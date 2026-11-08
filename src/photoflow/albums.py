"""Virtual date albums derived from the current index, without stored memberships."""

import re
from collections import Counter
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from photoflow.models import Photo, SavedAlbum
from photoflow.schemas import AlbumCreate, AlbumSummary, DateRangeRule


def eligible_photos() -> list[ColumnElement[bool]]:
    return [Photo.is_missing.is_(False), Photo.index_error.is_(None)]


def date_range_filters(start_date: date, end_date: date) -> list[ColumnElement[bool]]:
    """Both calendar dates are inclusive; compare timestamps without rounding."""
    filters = [*eligible_photos(), Photo.captured_at >= datetime.combine(start_date, time.min)]
    if end_date < date.max:
        filters.append(Photo.captured_at < datetime.combine(end_date + timedelta(days=1), time.min))
    return filters


def saved_album_summary(session: Session, album: SavedAlbum) -> AlbumSummary:
    count = session.scalar(
        select(func.count())
        .select_from(Photo)
        .where(*date_range_filters(album.start_date, album.end_date))
    )
    return AlbumSummary(
        id=f"saved-{album.id}",
        label=album.name,
        photo_count=count,
        rule=DateRangeRule(
            version=album.rule_version,
            type="date_range",
            start_date=album.start_date,
            end_date=album.end_date,
        ),
    )


def create_saved_album(session: Session, definition: AlbumCreate) -> AlbumSummary:
    album = SavedAlbum(
        name=definition.name,
        rule_version=definition.rule.version,
        start_date=definition.rule.start_date,
        end_date=definition.rule.end_date,
    )
    session.add(album)
    session.flush()
    summary = saved_album_summary(session, album)
    session.commit()
    return summary


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
    for calendar_month, count in groups:
        if calendar_month is None:
            undated = count
        else:
            months[calendar_month] = count
            years[calendar_month[:4]] += count

    albums = [AlbumSummary(id="all", label="All photos", photo_count=sum(years.values()) + undated)]
    for year in sorted(years, reverse=True):
        albums.append(AlbumSummary(id=f"year-{year}", label=year, photo_count=years[year]))
        for calendar_month in sorted(
            (month for month in months if month[:4] == year), reverse=True
        ):
            albums.append(
                AlbumSummary(
                    id=f"month-{calendar_month}",
                    label=calendar_month,
                    photo_count=months[calendar_month],
                )
            )
    albums.append(AlbumSummary(id="undated", label="Undated", photo_count=undated))
    for album in session.scalars(select(SavedAlbum).order_by(SavedAlbum.id)):
        albums.append(saved_album_summary(session, album))
    return albums


def album_filters(session: Session, album_id: str) -> list[ColumnElement[bool]]:
    """Resolve a rule ID to indexed date bounds, or raise ValueError for invalid IDs."""
    filters = eligible_photos()
    if album_id == "all":
        return filters
    if album_id == "undated":
        return [*filters, Photo.captured_at.is_(None)]
    if album_id.startswith("saved-"):
        match = re.fullmatch(r"saved-([1-9][0-9]{0,18})", album_id)
        if match is None or int(match[1]) > 2**63 - 1:
            raise ValueError("Invalid album ID")
        album = session.get(SavedAlbum, int(match[1]))
        if album is None:
            raise ValueError("Unknown album ID")
        return date_range_filters(album.start_date, album.end_date)

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
