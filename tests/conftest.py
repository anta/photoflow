import pytest

from photoflow.config import Settings
from photoflow.db import create_db_engine, migrate


@pytest.fixture
def settings(tmp_path):
    nas = tmp_path / "nas"
    nas.mkdir()
    return Settings(nas_root=nas, data_dir=tmp_path / "state", _env_file=None)


@pytest.fixture
def engine(settings):
    engine = create_db_engine(settings)
    migrate(engine)
    yield engine
    engine.dispose()
