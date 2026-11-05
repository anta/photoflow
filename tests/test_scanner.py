import os
from unittest.mock import patch

import pytest

from photoflow.nas import NasRoot
from photoflow.scanner import scan_photos


def test_recursive_scan_filters_extensions_and_uses_relative_paths(settings):
    for name in ("root.JPG", "nested/unicode-æ.png", ".hidden/a.tiff", "nested/a.webp"):
        path = settings.nas_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic")
    (settings.nas_root / "ignored.txt").write_text("not an image")
    (settings.nas_root / "ignored.heic").write_bytes(b"unsupported")
    results = list(scan_photos(NasRoot(settings.nas_root)))
    assert {item.relative_path for item in results} == {
        "root.JPG",
        "nested/unicode-æ.png",
        ".hidden/a.tiff",
        "nested/a.webp",
    }
    assert all(item.size_bytes == 9 for item in results)
    assert all(item.mtime_ns > 0 and item.ctime_ns > 0 for item in results)


def test_scan_skips_symlinks_cycles_and_special_files(settings, tmp_path):
    outside = tmp_path / "private.jpg"
    outside.write_bytes(b"private")
    (settings.nas_root / "escape.jpg").symlink_to(outside)
    (settings.nas_root / "cycle").symlink_to(settings.nas_root, target_is_directory=True)
    os.mkfifo(settings.nas_root / "pipe.jpg")
    assert list(scan_photos(NasRoot(settings.nas_root))) == []


def test_scan_reports_unreadable_root_and_raises_by_default(settings):
    nas = NasRoot(settings.nas_root)
    with patch("photoflow.scanner.os.scandir", side_effect=PermissionError("synthetic")):
        issues = []
        assert list(scan_photos(nas, on_error=issues.append)) == []
        assert len(issues) == 1
        assert issues[0].code == "unreadable_entry"
        with pytest.raises(PermissionError):
            list(scan_photos(nas))


def test_missing_root_is_an_error_even_with_callback(settings):
    nas = NasRoot(settings.nas_root)
    settings.nas_root.rmdir()
    with pytest.raises(FileNotFoundError):
        list(scan_photos(nas, on_error=lambda issue: None))
