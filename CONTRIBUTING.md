# Contributing

Use Python 3.12+ and install ExifTool. Follow the README setup or use
`uv sync --locked --extra dev --python 3.12` for the exact CI dependencies.

Before proposing changes:

```sh
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync pytest --cov=photoflow --cov-fail-under=90
uv build
```

Tests must generate their own images and metadata under pytest's temporary
directories. Do not point tests at a real photo library or commit photographic
fixtures, real metadata, production database files, `.env`, or personal logs.
Integration tests use a real ExifTool executable and must not silently skip it.

Keep source access read-only. Database schema changes require an Alembic revision
and upgrade/downgrade checks; do not use `create_all` to bypass migrations. Keep
library and state directories separate. Tests should verify observable behavior
and original-file preservation, including error paths where relevant.

Commit completed, tested units of work with descriptive messages. Future features
listed in [the roadmap](docs/roadmap.md) require a separate scope discussion; do not
slip file mutation, duplicate matching, or album/UI functionality into MVP fixes.

When changing dependencies, update `pyproject.toml`, run `uv lock`, then regenerate
the Docker requirements export and rerun checks:

```sh
uv export --locked --no-dev --no-emit-project --no-header --format requirements-txt --output-file requirements.lock > /dev/null
```

The CI tooling currently uses uv 0.13.7. Docker's base image and OS-level ExifTool
package should receive normal security updates; Python dependencies are locked.
