# Roadmap and CC-CLI v2 scope

The initial MVP is the foundation for a CC-CLI v2 submission. This repository does
not claim program acceptance, completed evaluation, or production hardening.

## Initial MVP delivered

1. Python package, README, MIT license, and development configuration.
2. Validated settings and read-only NAS file access.
3. SQLite schema and packaged Alembic migrations.
4. Recursive supported-photo scanner.
5. ExifTool metadata extraction with nullable optional fields.
6. Incremental indexing, failure recovery, and soft missing-file tracking.
7. Paginated REST browsing and photo details.
8. Metadata-free, orientation-correct thumbnails.
9. Synthetic unit and integration tests, including source-integrity checks.
10. Docker Compose, GitHub Actions, and setup/API/privacy/operations documentation.

Each milestone is represented by tested, descriptive local Git commits. Hosted CI
and Docker smoke checks must be run in their respective environments before a
release; their presence is not a claim that those external checks already ran.

## Future development tasks — not implemented

- **Virtual smart albums:** derive virtual membership from capture timestamps and
  GPS, define explicit timezone/location rules, and retain source files in place.
- **Duplicate detection:** evaluate content hashes and optional perceptual matching,
  explain match confidence, and add synthetic duplicate/near-duplicate tests.
- **Optional physical organization:** design a separate opt-in workflow with a dry
  run, clear destination preview, user approval, collision handling, and recovery
  before any source-file operation is introduced.
- **Album management web UI:** browse and manage virtual albums through a full web
  interface backed by dedicated album APIs.

Additional future considerations include authentication before network exposure,
HEIC/RAW support, cache lifecycle management, bulk metadata extraction, and indexing
performance measurements using generated datasets. These are design tasks, not
features of the current MVP.
