"""Explicit local maintenance and serving commands."""

import argparse
import json
import sys
from dataclasses import asdict

import uvicorn
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from photoflow.config import Settings
from photoflow.db import bind_library, create_db_engine, migrate
from photoflow.indexer import index_library
from photoflow.locking import index_lock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="photoflow", description="Read-only NAS photo indexing")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="Upgrade the writable SQLite index to the latest schema")
    index = commands.add_parser("index", help="Incrementally index supported photos")
    index.add_argument("--force", action="store_true", help="Re-extract metadata for every photo")
    commands.add_parser("serve", help="Run the photo browsing API")
    args = parser.parse_args(argv)
    try:
        settings = Settings()
        if args.command == "migrate":
            from sqlalchemy.orm import Session

            with index_lock(settings):
                engine = create_db_engine(settings)
                try:
                    migrate(engine)
                    with Session(engine) as session:
                        bind_library(session, settings)
                finally:
                    engine.dispose()
            print("Database is up to date.")
        elif args.command == "index":
            result = index_library(settings, force=args.force)
            print(json.dumps(asdict(result)))
            return 0 if result.status == "completed" else 1
        else:
            from photoflow.main import create_app

            uvicorn.run(create_app(), host=settings.host, port=settings.port, access_log=False)
    except ValidationError:
        print(
            "Invalid configuration; check PHOTOFLOW_* settings and directory separation.",
            file=sys.stderr,
        )
        return 1
    except SQLAlchemyError:
        print(
            "Database operation failed; check writable storage and migration state.",
            file=sys.stderr,
        )
        return 1
    except (OSError, RuntimeError) as error:
        # Runtime messages contain operational guidance, never raw ExifTool output.
        message = str(error) if isinstance(error, RuntimeError) else "Storage operation failed."
        print(message, file=sys.stderr)
        return 1
    return 0
