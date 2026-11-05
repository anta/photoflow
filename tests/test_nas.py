import os

import pytest

from photoflow.nas import NasRoot, UnsafePathError


def test_photo_open_is_read_only(settings):
    photo = settings.nas_root / "photo.jpg"
    photo.write_bytes(b"synthetic")
    before = photo.stat()
    with NasRoot(settings.nas_root).open_photo("photo.jpg") as stream:
        assert stream.read() == b"synthetic"
        assert not stream.writable()
    assert photo.read_bytes() == b"synthetic"
    assert photo.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize("path", ["", ".", "../secret.jpg", "/etc/passwd", "a/../../b", "x\x00"])
def test_rejects_unsafe_paths(settings, path):
    with pytest.raises(UnsafePathError), NasRoot(settings.nas_root).open_photo(path):
        pytest.fail("Unsafe path opened")


@pytest.mark.parametrize("directory", [False, True])
def test_refuses_symlinks(settings, tmp_path, directory):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.jpg").write_bytes(b"private")
    link = settings.nas_root / "link"
    link.symlink_to(outside if directory else outside / "secret.jpg")
    with (
        pytest.raises(OSError),
        NasRoot(settings.nas_root).open_photo("link/secret.jpg" if directory else "link"),
    ):
        pytest.fail("Symlink opened")


def test_refuses_fifo_without_blocking(settings):
    os.mkfifo(settings.nas_root / "pipe.jpg")
    with pytest.raises(UnsafePathError), NasRoot(settings.nas_root).open_photo("pipe.jpg"):
        pytest.fail("FIFO opened")
