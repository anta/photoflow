"""Alembic environment shared by the CLI and Python migration helper."""

from alembic import context

from photoflow.config import Settings
from photoflow.db import create_db_engine
from photoflow.models import Base


def run_migrations(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("PhotoFlow migrations require an online SQLite connection")

connection = context.config.attributes.get("connection")
if connection is not None:
    run_migrations(connection)
else:
    engine = create_db_engine(Settings())
    try:
        with engine.connect() as connection:
            run_migrations(connection)
    finally:
        engine.dispose()
