"""Serialize local indexing processes on the writable state volume."""

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager

from photoflow.config import Settings


@contextmanager
def index_lock(settings: Settings) -> Iterator[None]:
    settings.prepare_data_dir()
    with (settings.data_dir / "index.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("An index or migration is already running") from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
