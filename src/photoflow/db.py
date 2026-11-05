"""SQLite engine, explicit migrations, and library binding."""

import hashlib
import os
from importlib.resources import files

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session

from photoflow.config import Settings
from photoflow.models import Library


def create_db_engine(settings: Settings) -> Engine:
    settings.prepare_data_dir()
    engine = create_engine(
        URL.create("sqlite", database=str(settings.database_path)),
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    return engine


def migration_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(files("photoflow").joinpath("migrations")))
    return config


def migrate(engine: Engine, revision: str = "head") -> None:
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        connection.commit()
    with engine.begin() as connection:
        config = migration_config()
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def require_current_schema(engine: Engine) -> None:
    expected = ScriptDirectory.from_config(migration_config()).get_heads()
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_heads()
    if set(expected) != set(current):
        raise RuntimeError("Database migration required; run 'photoflow migrate'")


def bind_library(session: Session, settings: Settings) -> None:
    fingerprint = hashlib.sha256(os.fsencode(settings.nas_root)).hexdigest()
    library = session.get(Library, 1)
    if library is None:
        session.add(Library(id=1, root_fingerprint=fingerprint))
        session.commit()
    elif library.root_fingerprint != fingerprint:
        raise RuntimeError("Database belongs to another NAS root; use a separate data directory")
