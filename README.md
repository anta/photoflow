# PhotoFlow

Privacy-first, self-hosted photo indexing for NAS libraries. PhotoFlow reads your
existing photo tree, stores selected metadata in SQLite, and serves a browsing API
with thumbnails. Original photo contents, filenames, and organization stay untouched.
No cloud service, telemetry, or external account is required.

This is the initial open-source MVP intended for the **CC-CLI v2** program. Virtual
smart albums, duplicate detection, physical file organization, and a full album web
interface are deliberately reserved for [future development](docs/roadmap.md).

## What's implemented

- Python 3.12+, FastAPI, SQLAlchemy, SQLite/WAL, and explicit Alembic migrations.
- Validated configuration with separate NAS and writable state directories.
- Recursive JPEG, PNG, TIFF, and WebP scanning, including nested and Unicode paths.
- ExifTool extraction of capture time, timezone offset, GPS, dimensions, orientation,
  and camera make/model; absent metadata stays null.
- Incremental indexing, retryable file failures, missing-file tracking, and a process lock.
- Paginated photo browsing, literal path search, photo details, health checks, and OpenAPI.
- Orientation-correct Pillow thumbnails with EXIF and other source metadata removed.
- Synthetic-image unit and integration tests, Docker Compose, and GitHub Actions.

There is no upload, delete, original-file download, or file-moving endpoint.

## Local setup

Linux and macOS are supported. Install Python 3.12+ and ExifTool first:

```sh
# Debian / Ubuntu
sudo apt-get install libimage-exiftool-perl
# macOS (alternative)
brew install exiftool
```

From the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

Edit `.env`: set `PHOTOFLOW_NAS_ROOT` to an existing photo directory **outside this
repository**, and `PHOTOFLOW_DATA_DIR` to a separate writable directory. Then:

```sh
photoflow migrate
photoflow index
photoflow serve
```

Browse API documentation at <http://127.0.0.1:8000/docs> or try:

```sh
curl 'http://127.0.0.1:8000/api/v1/photos?limit=20&offset=0'
curl 'http://127.0.0.1:8000/api/v1/photos/1'
curl 'http://127.0.0.1:8000/api/v1/photos/1/thumbnail' -o /tmp/photoflow-thumbnail.jpg
```

Run `photoflow index` again to discover changes, or `photoflow index --force` to
re-extract all metadata. Indexing returns a JSON summary and exits nonzero for a
partial or failed scan. Browsing never starts an index scan.

## Docker Compose

Set `PHOTOFLOW_NAS_ROOT` in `.env` to an existing absolute host path. The container
runs as UID/GID `10001:10001`, which needs read/search permission on that tree.

```sh
docker compose up --build -d --wait
docker compose exec photoflow photoflow index
```

Compose mounts the photo directory **read-only**, keeps SQLite and thumbnails in
the `photoflow_state` volume, and publishes the API on `127.0.0.1:8000`. Container
startup upgrades the database before serving; indexing remains manual. See
[deployment](docs/deployment.md) for NAS permissions, backups, upgrades, and smoke tests.

## Tests and reproducible development

All test images and metadata are generated under pytest temporary directories.
Tests require ExifTool and never use the configured real NAS directory.

```sh
pytest --cov=photoflow --cov-fail-under=90
ruff check .
ruff format --check .
```

For the exact dependency set used by CI, install [uv](https://docs.astral.sh/uv/)
and run `uv sync --locked --extra dev --python 3.12`, then prefix commands with
`uv run --no-sync`. Docker uses the hash-pinned `requirements.lock` exported from
`uv.lock`. CI tests Python 3.12, 3.13, and 3.14 and includes a Compose smoke job.

## Privacy and limits

The API is unauthenticated and intended for a trusted local deployment. Keep the
default loopback binding, or put authentication and TLS in a reverse proxy before
allowing access from other machines. The SQLite index contains private capture
times, relative paths, and GPS coordinates; protect it and its backups just like
photos. Thumbnails remain private visual data even after metadata removal.

Application code opens originals read-only and skips internal symlinks. Native
filesystem reads may still update access times; a read-only NAS mount provides
the operating-system boundary. Only the listed formats are supported; HEIC, RAW,
video, album generation, duplicate matching, and file organization are out of scope.

Never commit private photos, local databases, `.env`, logs, or sensitive metadata.
Read [architecture](docs/architecture.md), [API](docs/api.md),
[privacy](docs/privacy.md), and [contributing](CONTRIBUTING.md) for details.

## License

[MIT](LICENSE).
