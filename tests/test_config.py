import pytest
from pydantic import ValidationError

from photoflow.config import Settings


def test_environment_configuration(tmp_path, monkeypatch):
    nas = tmp_path / "photos"
    nas.mkdir()
    monkeypatch.setenv("PHOTOFLOW_NAS_ROOT", str(nas))
    monkeypatch.setenv("PHOTOFLOW_DATA_DIR", str(tmp_path / "state"))
    config = Settings(_env_file=None)
    assert config.nas_root == nas
    assert config.database_path == tmp_path / "state" / "photoflow.sqlite3"
    assert not config.data_dir.exists()
    config.prepare_data_dir()
    assert config.data_dir.is_dir()


def test_missing_nas_is_not_created(tmp_path):
    with pytest.raises(ValidationError, match="existing directory"):
        Settings(nas_root=tmp_path / "missing", _env_file=None)
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("relative", [".", "cache", ".."])
def test_writable_data_must_not_overlap_nas(settings, relative):
    with pytest.raises(ValidationError, match="must not overlap"):
        Settings(nas_root=settings.nas_root, data_dir=settings.nas_root / relative, _env_file=None)


def test_symlink_cannot_hide_data_overlap(settings, tmp_path):
    link = tmp_path / "link"
    link.symlink_to(settings.nas_root, target_is_directory=True)
    with pytest.raises(ValidationError, match="must not overlap"):
        Settings(nas_root=settings.nas_root, data_dir=link / "cache", _env_file=None)


@pytest.mark.parametrize("value", [0, 4096])
def test_invalid_thumbnail_size(settings, value):
    with pytest.raises(ValidationError):
        Settings(
            nas_root=settings.nas_root,
            data_dir=settings.data_dir,
            thumbnail_size=value,
            _env_file=None,
        )
