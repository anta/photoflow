# Deployment and operations

## Configuration

Settings load from environment variables and an optional `.env` in the current
directory. Environment variables take precedence. Paths are resolved at startup.

| Variable | Default | Meaning |
| --- | --- | --- |
| `PHOTOFLOW_NAS_ROOT` | `/photos` | Existing, readable source directory |
| `PHOTOFLOW_DATA_DIR` | `./data` | Writable local state, separate from the source tree |
| `PHOTOFLOW_EXIFTOOL_PATH` | `exiftool` | Executable name or absolute executable path |
| `PHOTOFLOW_EXIFTOOL_TIMEOUT` | `30` | Per-file subprocess timeout, seconds, up to 300 |
| `PHOTOFLOW_THUMBNAIL_SIZE` | `400` | Longest thumbnail edge, 64–2048 pixels |
| `PHOTOFLOW_THUMBNAIL_QUALITY` | `85` | JPEG quality, 50–95 |
| `PHOTOFLOW_HOST` | `127.0.0.1` | Native server bind address |
| `PHOTOFLOW_PORT` | `8000` | Native port or Compose published host port |

The state directory must neither contain the NAS root nor be inside it. SQLite
is stored at `DATA_DIR/photoflow.sqlite3`, the thumbnail cache at
`DATA_DIR/thumbnails`, and the advisory process lock at `DATA_DIR/index.lock`.
Keep state on local storage with working POSIX locks; do not put SQLite/WAL on an
NFS or SMB share. One state directory indexes one canonical NAS path. A different
root requires a different state directory; native and container root paths differ.

## Container deployment

Requirements: Docker Engine with Compose v2 and a mounted NAS photo directory.
`docker compose config --quiet` validates configuration without starting anything.
The bind mount refuses to create a missing host source path. Verify that the NAS
is actually mounted before scanning; an empty mountpoint can appear to be an empty
library and cause records to be marked missing. Missing records are retained.

```sh
cp .env.example .env
# Edit PHOTOFLOW_NAS_ROOT to the real host path before continuing.
docker compose config --quiet
docker compose up --build -d --wait
docker compose exec photoflow photoflow index
curl http://127.0.0.1:8000/health
```

Compose uses a read-only root filesystem and NAS mount, an unprivileged user,
dropped capabilities, and a small temporary filesystem. `/data` is the writable
named volume. For Compose, `PHOTOFLOW_DATA_DIR`, `PHOTOFLOW_HOST`, and the ExifTool
path are fixed inside the container; editing their native `.env` values does not
change the container layout. Host port and thumbnail settings are passed through.

UID 10001 needs read access to files and execute/search access to directories.
Use a read-only NAS account or an appropriate supplemental group. For example,
an administrator can add a local `compose.override.yaml` with `group_add` for
the existing NAS reader GID. Do not grant source write permissions to PhotoFlow.
If replacing the named state volume with a host bind mount, provision that
directory for UID/GID 10001 with mode 0700 first.

The port binds only to loopback. For remote browsing, configure a reverse proxy
with authentication and TLS and restrict access to a trusted network. There is no
built-in user/account system in this MVP. Do not expose the API directly online.

## Indexing, recovery, albums, and thumbnails

```sh
docker compose exec photoflow photoflow index
docker compose exec photoflow photoflow index --force
```

An index scan prints counts, not source paths or metadata. Each successful file is
committed independently. A file failure does not block the rest of the library;
rerunning retries failed files and skips unchanged ones. An advisory lock rejects
concurrent indexing and migrations. An interrupted run is marked failed by the
next indexer. A traversal error suppresses the final missing-file sweep.

Missing originals are retained as `is_missing=true`, hidden from default listing,
and become visible again when successfully found in a later scan. Renames create a
new path record and mark the old one missing; no rename or duplicate matching is
performed. A failed update retains older metadata with `index_error` set until a
successful retry. Failed new files are counted but not added to the photo table.

Automatic and saved album membership reflects those index updates without a
rebuild. Missing/error records are excluded from every album. Saved names and date
rules live in SQLite and remain available even with no matching photos; protect
them with the index. The API can create definitions but scanning remains manual.

Thumbnails are lazy JPEGs. The cache key includes the record, file stat signature,
size/quality settings, and rendering version. A changed source returns HTTP 409
until reindexed. Old cache generations are not garbage-collected in this MVP.
With the service stopped, the thumbnail cache alone can be removed and will
regenerate. Never remove or modify files in the NAS to manage the cache.

## Upgrades and backups

Stop serving and indexing before upgrading. Back up the state volume while
stopped, then rebuild and start Compose. Startup runs Alembic upgrades before the
API is available. Native deployments run `photoflow migrate` explicitly before
`photoflow serve`. Back up before migrations; schema downgrades can discard index
data. Alembic development commands are available via `alembic.ini`.

Revision `0002` introduces saved date-range album definitions. It does not rewrite
existing photo records. Downgrading to `0001` drops saved definitions while keeping
photos and scan history; a later upgrade does not restore those definitions.

The complete stopped state volume is safe to copy. For live SQLite backups, use
SQLite's backup API; copying only the main database while WAL is active can omit
committed changes. Thumbnails can be regenerated, but backups still contain private
visual and metadata data. Original-photo backups remain the NAS owner's responsibility.

## Container smoke check

```sh
docker build -t photoflow:local .
bash scripts/docker-smoke.sh
```

The script creates a temporary PNG, starts an isolated Compose project with a
random loopback port, indexes it, checks browsing, date/saved albums, and thumbnails,
and verifies that source writes fail. Its temporary containers and volumes are removed on exit.
It never uses `.env` or real photo paths. GitHub Actions runs this same smoke check.
