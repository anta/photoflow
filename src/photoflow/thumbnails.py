"""Generate orientation-correct JPEG thumbnails in the writable cache only."""

import hashlib
import io
import os
import tempfile
import warnings
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError

from photoflow.config import Settings
from photoflow.models import Photo
from photoflow.nas import NasRoot, UnsafePathError
from photoflow.scanner import PhotoFile


class ThumbnailError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class ThumbnailService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.nas = NasRoot(settings.nas_root)

    def cache_path(self, photo: Photo) -> Path:
        # This identifies a rendering, not photo contents or duplicate photos.
        identity = (
            f"v1:{photo.id}:{photo.relative_path}:{photo.size_bytes}:{photo.mtime_ns}:"
            f"{photo.ctime_ns}:{self.settings.thumbnail_size}:{self.settings.thumbnail_quality}"
        )
        key = hashlib.sha256(identity.encode()).hexdigest()
        return self.settings.thumbnail_dir / key[:2] / f"{key}.jpg"

    @staticmethod
    def _check_source(source: BinaryIO, photo: Photo) -> None:
        actual = PhotoFile.from_stat(photo.relative_path, os.fstat(source.fileno()))
        if actual.signature != (photo.size_bytes, photo.mtime_ns, photo.ctime_ns):
            raise ThumbnailError(409, "Photo changed; run indexing again")

    def _render(self, source: BinaryIO) -> bytes:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(source) as original:
                    original.seek(0)
                    # JPEG decoders can reduce resolution before allocating the full raster.
                    original.draft(
                        "RGB", (self.settings.thumbnail_size, self.settings.thumbnail_size)
                    )
                    oriented = ImageOps.exif_transpose(original)
                    oriented.thumbnail(
                        (self.settings.thumbnail_size, self.settings.thumbnail_size),
                        Image.Resampling.LANCZOS,
                    )
                    if oriented.mode in {"RGBA", "LA"} or "transparency" in oriented.info:
                        rgba = oriented.convert("RGBA")
                        image = Image.new("RGB", rgba.size, "white")
                        image.paste(rgba, mask=rgba.getchannel("A"))
                    else:
                        image = oriented.convert("RGB")
                    image.info.clear()
                    output = io.BytesIO()
                    image.save(output, format="JPEG", quality=self.settings.thumbnail_quality)
                    return output.getvalue()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise ThumbnailError(413, "Photo exceeds safe decoding size") from error
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as error:
            raise ThumbnailError(422, "Photo cannot be decoded") from error

    @staticmethod
    def _store(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".thumbnail-", delete=False
            ) as f:
                temporary = Path(f.name)
                f.write(content)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def get(self, photo: Photo) -> bytes:
        if photo.is_missing:
            raise ThumbnailError(404, "Photo is missing from the library")
        if photo.index_error is not None:
            raise ThumbnailError(409, "Photo needs successful indexing before thumbnail generation")
        try:
            self.settings.prepare_data_dir()
            with self.nas.open_photo(photo.relative_path) as source:
                self._check_source(source, photo)
                path = self.cache_path(photo)
                if path.is_symlink() or not path.parent.resolve().is_relative_to(
                    self.settings.data_dir
                ):
                    raise ThumbnailError(503, "Unsafe thumbnail cache path")
                try:
                    content = path.read_bytes()
                except FileNotFoundError:
                    content = self._render(source)
                    self._check_source(source, photo)
                    self._store(path, content)
                self._check_source(source, photo)
                return content
        except FileNotFoundError as error:
            raise ThumbnailError(404, "Photo is unavailable; run indexing again") from error
        except UnsafePathError as error:
            raise ThumbnailError(404, "Photo is unavailable") from error
        except OSError as error:
            raise ThumbnailError(503, "Photo or thumbnail storage unavailable") from error
        except RuntimeError as error:
            if isinstance(error, ThumbnailError):
                raise
            raise ThumbnailError(503, "Thumbnail storage unavailable") from error
