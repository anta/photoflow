import pytest

from photoflow.config import Settings


@pytest.fixture
def settings(tmp_path):
    nas = tmp_path / "nas"
    nas.mkdir()
    return Settings(nas_root=nas, data_dir=tmp_path / "state", _env_file=None)
