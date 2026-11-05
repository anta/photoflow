"""Read-only photo browsing routes."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from photoflow.models import Photo
from photoflow.schemas import PhotoDetail, PhotoPage

router = APIRouter(prefix="/api/v1", tags=["photos"])


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


DatabaseSession = Annotated[Session, Depends(get_session)]
PhotoId = Annotated[int, Path(ge=1)]


@router.get("/photos", response_model=PhotoPage)
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
    total = session.scalar(select(func.count()).select_from(Photo).where(*filters))
    photos = session.scalars(
        select(Photo)
        .where(*filters)
        .order_by(Photo.relative_path, Photo.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return PhotoPage(items=photos, total=total, limit=limit, offset=offset)


def find_photo(session: Session, photo_id: int) -> Photo:
    photo = session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    return photo


@router.get("/photos/{photo_id}", response_model=PhotoDetail)
def get_photo(photo_id: PhotoId, session: DatabaseSession) -> Photo:
    return find_photo(session, photo_id)
