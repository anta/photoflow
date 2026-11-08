# Architecture

PhotoFlow has one local library per SQLite database. The NAS root is an input-only
tree; the separate writable state directory contains the index, lock, and cache.

| Module | Responsibility |
| --- | --- |
| `config.py` | Environment settings, directory validation, state path separation |
| `nas.py` | Read-only regular-file opens through directory descriptors |
| `scanner.py` | Streaming recursive enumeration, extension filtering, scan issues |
| `metadata.py` | Bounded ExifTool subprocess, JSON parsing, metadata allowlist |
| `models.py`, `db.py`, `migrations/` | SQLAlchemy tables, sessions, Alembic lifecycle |
| `indexer.py`, `locking.py` | Serialized incremental indexing and recovery |
| `albums.py` | Query-time calendar album summaries and membership rules |
| `api.py`, `schemas.py`, `main.py` | FastAPI browsing and startup/readiness checks |
| `thumbnails.py` | Pillow rendering and atomic cache publication |
| `cli.py` | `migrate`, `index [--force]`, and `serve` |

## Data flow

1. Settings canonicalize the configured paths and reject overlapping state/NAS trees.
2. Explicit migrations create `photos`, `scan_runs`, and a singleton `library` binding.
3. The scanner visits regular files with case-insensitive supported extensions.
4. Indexing compares size, nanosecond mtime, and ctime with the existing path record.
5. Changed/new files are opened read-only and fed to ExifTool via stdin. Only a
   selected metadata set is retained. Pre/post-read stat checks reject unstable files.
6. Each successful file commits independently. Seen markers allow a final soft
   missing-file sweep only after a complete traversal. Per-file extraction errors
   remain retryable; directory traversal errors suppress the sweep.
7. FastAPI reads the database through short-lived SQLAlchemy sessions. Thumbnail
   requests verify the indexed source signature and produce a private cached JPEG.
8. Virtual album queries group the current eligible records by capture year/month
   or a null capture time. There is no album directory, copied photo, or membership table.

`library.root_fingerprint` hashes the configured canonical root path to prevent
accidentally using one database with a different path. It is not a content hash,
mount identity check, or duplicate detection. File content hashes are not computed
by the application. Photo IDs are never reused within the same SQLite database.

SQLite uses WAL, a busy timeout, foreign keys, and indexed capture-time, missing,
and seen-marker columns. An initial Alembic migration is packaged inside the wheel,
so installed CLI commands work outside the source checkout. Startup requires the
current schema; it does not silently call SQLAlchemy `create_all`.

Directory/file opens use POSIX descriptors with `O_NOFOLLOW`. Internal symlinks,
FIFOs, and devices are skipped or rejected. Descriptor traversal prevents an
internal path swap from escaping through a symlink. The administrator controls
the configured root, its ancestor directories, and the writable state directory;
those trusted paths must not be rearranged by untrusted processes. Managed state
symlinks and cache shards resolving outside state are rejected. A read-only mount
provides an additional kernel-enforced source boundary.

Thumbnail cache keys identify a particular source record/stat signature/rendering
configuration. JPEGs are orientation-correct, bounded in size, never upscaled,
flattened against white when transparent, and saved without source EXIF/XMP/ICC.
Pillow's decompression-bomb checks remain enabled. Temporary cache writes are
atomically renamed; simultaneous rendering can safely converge on one cache file.

## Virtual date albums

Albums derive their membership at query time from `photos`: `all`, `undated`,
`year-YYYY`, and `month-YYYY-MM`. A record can appear in all-photos, a year, and a
month at once while retaining one Photo ID. The existing schema is sufficient;
this feature requires no new migration or rebuild step.

Both summaries and contents exclude `is_missing=true` and non-null `index_error`.
Retained metadata from failed indexing therefore cannot silently generate current
album membership. The ordinary photo/detail APIs still expose those records for
diagnosis. Successful rescans, missing-file sweeps, and retries change album results
as their database updates commit. Browsing never starts indexing or opens originals.

Capture timestamps are stored as naive ISO camera wall times in SQLite, with a
separate optional offset. Summary queries group the stored year/month text without
date-function rounding; content queries use inclusive start and exclusive end
bounds on the indexed `captured_at` column. Neither applies offsets or server
timezones. Unknown/invalid capture dates enter Undated; mtime is never substituted.
Album counts and pages use identical eligibility and date rules. Requests are not
a snapshot across concurrent indexing; list counts or page positions may change.

## Deliberate limits

- Supported suffixes: `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff`, `.webp`. HEIC, camera
  RAW, video, and other formats are skipped. Multi-frame images use the first frame.
- One ExifTool process per changed file; no background queue, watcher, scheduler,
  distributed workers, or performance claims for very large libraries yet.
- Incremental detection depends on filesystem stat fidelity. `--force` re-extracts
  metadata; there is no content-integrity or duplicate-hash pass.
- ExifTool-readable image headers can be indexed even if later pixel decoding
  fails. Thumbnail errors do not modify source files.
- No cache garbage collection, hard record deletion, rename matching, or scan
  history API. Missing records and old cache entries remain until state is rebuilt.
- No authentication, multi-user tenancy, saved/custom albums, GPS grouping,
  duplicate grouping, file organization, or full browser UI. See the [roadmap](roadmap.md).
