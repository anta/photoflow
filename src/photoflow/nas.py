"""Read-only, descriptor-based access to regular files below a NAS root.

Opening each path component with O_NOFOLLOW prevents symlink traversal, including
when a directory entry changes between scanning and opening a photo. Linux and
macOS are supported; the original tree is never opened with write flags.
"""

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO


class UnsafePathError(ValueError):
    """A requested path is not a regular file inside the configured NAS."""


class NasRoot:
    def __init__(self, root: Path):
        # Settings resolves an administrator's configured root once. Do not follow
        # a replacement root symlink introduced after that validation.
        self.root = root.absolute()
        directory_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.close(directory_fd)

    @staticmethod
    def _parts(relative_path: str) -> tuple[str, ...]:
        path = PurePosixPath(relative_path)
        if (
            not relative_path
            or "\x00" in relative_path
            or path.is_absolute()
            or ".." in path.parts
            or not path.parts
        ):
            raise UnsafePathError("Expected a nonempty relative photo path")
        return path.parts

    @contextmanager
    def open_photo(self, relative_path: str) -> Iterator[BinaryIO]:
        parts = self._parts(relative_path)
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory_fd = os.open(self.root, directory_flags)
        try:
            for part in parts[:-1]:
                child_fd = os.open(part, directory_flags, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = child_fd
            file_fd = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd
            )
            try:
                if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                    raise UnsafePathError("Only regular photo files may be read")
                stream = os.fdopen(file_fd, "rb")
            except BaseException:
                os.close(file_fd)
                raise
            with stream:
                yield stream
        finally:
            os.close(directory_fd)
