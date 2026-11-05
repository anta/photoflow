"""Stream supported regular photo files without following symbolic links."""

import os
import stat
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath

from photoflow.nas import NasRoot

SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"})


@dataclass(frozen=True)
class PhotoFile:
    relative_path: str
    size_bytes: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def from_stat(cls, relative_path: str, info: os.stat_result) -> "PhotoFile":
        return cls(relative_path, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    @property
    def signature(self) -> tuple[int, int, int]:
        return self.size_bytes, self.mtime_ns, self.ctime_ns


@dataclass(frozen=True)
class ScanIssue:
    relative_path: str
    code: str


def scan_photos(
    nas: NasRoot, on_error: Callable[[ScanIssue], None] | None = None
) -> Iterator[PhotoFile]:
    """Walk by directory descriptors; surface errors to prevent unsafe missing sweeps.

    Hidden directories are included. Only the supported extension set is selected;
    actual image validity is checked later by metadata extraction and decoding.
    Directory enumeration is streaming, with memory proportional to tree depth.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def report(relative_path: str, error: OSError) -> None:
        if on_error is None:
            raise error
        on_error(ScanIssue(relative_path, "unreadable_entry"))

    def walk(directory_fd: int, parent: str) -> Iterator[PhotoFile]:
        try:
            with os.scandir(directory_fd) as entries:
                for entry in entries:
                    relative_path = f"{parent}/{entry.name}" if parent else entry.name
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISDIR(info.st_mode):
                            child_fd = os.open(entry.name, flags, dir_fd=directory_fd)
                            try:
                                yield from walk(child_fd, relative_path)
                            finally:
                                os.close(child_fd)
                        elif (
                            stat.S_ISREG(info.st_mode)
                            and PurePosixPath(entry.name).suffix.lower() in SUPPORTED_EXTENSIONS
                        ):
                            yield PhotoFile.from_stat(relative_path, info)
                    except OSError as error:
                        report(relative_path, error)
        except OSError as error:
            report(parent, error)

    # Root failure always aborts; an unavailable mount is never an empty library.
    root_fd = os.open(nas.root, flags)
    try:
        yield from walk(root_fd, "")
    finally:
        os.close(root_fd)
