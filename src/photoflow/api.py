"""Photo browsing and virtual album definition routes; originals stay read-only."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from photoflow.albums import album_filters, create_saved_album, list_albums
from photoflow.models import Photo
from photoflow.schemas import AlbumCreate, AlbumSummary, PhotoDetail, PhotoPage
from photoflow.thumbnails import ThumbnailError, ThumbnailService

router = APIRouter(prefix="/api/v1")


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


DatabaseSession = Annotated[Session, Depends(get_session)]
PhotoId = Annotated[int, Path(ge=1)]


def photo_page(
    session: Session, filters: list[ColumnElement[bool]], limit: int, offset: int
) -> PhotoPage:
    total = session.scalar(select(func.count()).select_from(Photo).where(*filters))
    photos = session.scalars(
        select(Photo)
        .where(*filters)
        .order_by(Photo.relative_path, Photo.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return PhotoPage(items=photos, total=total, limit=limit, offset=offset)


@router.get(
    "/albums", response_model=list[AlbumSummary], response_model_exclude_none=True, tags=["albums"]
)
def get_albums(session: DatabaseSession) -> list[AlbumSummary]:
    return list_albums(session)


@router.post("/albums", response_model=AlbumSummary, status_code=201, tags=["albums"])
def post_album(definition: AlbumCreate, session: DatabaseSession) -> AlbumSummary:
    return create_saved_album(session, definition)


@router.get("/albums/{album_id}/photos", response_model=PhotoPage, tags=["albums"])
def get_album_photos(
    album_id: str,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PhotoPage:
    try:
        filters = album_filters(session, album_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Album not found") from error
    page = photo_page(session, filters, limit, offset)
    if page.total == 0 and album_id.startswith(("year-", "month-")):
        raise HTTPException(status_code=404, detail="Album not found")
    return page


@router.get("/photos", response_model=PhotoPage, tags=["photos"])
def list_photos(
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    query: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    include_missing: bool = False,
) -> PhotoPage:
    filters = []
    if not include_missing:
        filters.append(Photo.is_missing.is_(False))
    if query is not None:
        filters.append(Photo.relative_path.contains(query, autoescape=True))
    return photo_page(session, filters, limit, offset)


def find_photo(session: Session, photo_id: int) -> Photo:
    photo = session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    return photo


@router.get("/photos/{photo_id}", response_model=PhotoDetail, tags=["photos"])
def get_photo(photo_id: PhotoId, session: DatabaseSession) -> Photo:
    return find_photo(session, photo_id)


@router.get(
    "/photos/{photo_id}/thumbnail",
    response_class=Response,
    tags=["photos"],
    responses={
        200: {"content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
def get_thumbnail(photo_id: PhotoId, session: DatabaseSession, request: Request) -> Response:
    photo = find_photo(session, photo_id)
    try:
        content = ThumbnailService(request.app.state.settings).get(photo)
    except ThumbnailError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=503, detail="Photo storage unavailable") from error
    return Response(content=content, media_type="image/jpeg")
