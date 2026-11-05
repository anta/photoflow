from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from photoflow.db import (
    bind_library,
    create_db_engine,
    migrate,
    migration_config,
    require_current_schema,
)
from photoflow.models import Base, Photo


@pytest.fixture
def engine(settings):
    engine = create_db_engine(settings)
    migrate(engine)
    yield engine
    engine.dispose()


def test_migrations_roundtrip_and_match_models(settings):
    engine = create_db_engine(settings)
    try:
        with pytest.raises(RuntimeError, match="migration required"):
            require_current_schema(engine)
        migrate(engine)
        migrate(engine)
        require_current_schema(engine)
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
            assert connection.scalar(text("PRAGMA journal_mode")) == "wal"
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        with engine.begin() as connection:
            config = migration_config()
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
        assert "photos" not in inspect(engine).get_table_names()
        migrate(engine)
        require_current_schema(engine)
    finally:
        engine.dispose()


def test_library_binding_rejects_another_root(engine, settings, tmp_path):
    with Session(engine) as session:
        bind_library(session, settings)
        bind_library(session, settings)
        other = tmp_path / "other"
        other.mkdir()
        with pytest.raises(RuntimeError, match="another NAS root"):
            bind_library(session, settings.model_copy(update={"nas_root": other}))


def test_path_unique_and_photo_values_constrained(engine):
    def photo(**changes):
        values = dict(
            relative_path="generated.jpg",
            size_bytes=12,
            mtime_ns=1,
            ctime_ns=1,
            indexed_at=datetime.now(UTC).replace(tzinfo=None),
            last_seen_scan="synthetic",
        )
        return Photo(**(values | changes))

    with Session(engine) as session:
        session.add(photo())
        session.commit()
        for changes in (
            {},
            {"relative_path": "negative.jpg", "size_bytes": -1},
            {"relative_path": "gps.jpg", "latitude": 91},
        ):
            session.add(photo(**changes))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
