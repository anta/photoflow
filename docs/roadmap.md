# PhotoFlow roadmap

PhotoFlow provides read-only photo indexing, metadata browsing, thumbnails, and
automatic date albums and saved date-range albums. Development builds on that
foundation while preserving source-file safety and local control of photo data.

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

Hosted CI and Docker smoke checks must pass in their respective environments
before a release. Their configuration alone does not establish release readiness.

## Date-based virtual albums delivered

The single-source API now lists all-photos, year, month, and undated albums with
stable rule IDs, counts, and paginated contents. Membership comes from the current
index, uses the camera's stored calendar date, and excludes missing/error records.
No photo copies, membership tables, or source-file changes are needed. Synthetic
tests cover date boundaries, offsets, reindexing, recovery, and source integrity.

## Saved date-range albums delivered

Named, version-1 date-range definitions are persisted through an Alembic migration.
The API creates, lists, and browses them with stable IDs and inclusive calendar
dates. Albums can overlap and remain available when empty. Membership is queried
from the current index and follows rescans without file copies or source changes.
Synthetic tests cover validation, persistence, upgrades, overlaps, and reindexing.

## Next milestones — not implemented

1. **Extend saved albums and add GPS grouping:** add editing/deletion when needed,
   then deterministic offline geographic rules with explicit missing-GPS and
   boundary behavior. No external geocoding is planned for this step.
2. **Automatic setup and ongoing indexing:** simplify initial folder/state setup,
   expose progress, and add reliable periodic rescans while preserving process
   locking, partial-scan safeguards, and NAS availability checks.
3. **Small album browser and folder onboarding:** browse album counts, paginated
   photos, and thumbnails; select only administrator-approved server locations.
   Keep loopback defaults pending an authentication/network design.
4. **Multiple source roots, if needed:** introduce per-source binding and scan
   scope, migrate existing Photo IDs, and handle identical relative paths and
   disconnected sources without affecting other sources' records or albums.

Additional future considerations include authentication before network exposure,
HEIC/RAW support, cache lifecycle management, bulk metadata extraction, and indexing
performance measurements using generated datasets. Duplicate detection and physical
file organization are outside the next milestones; any later file-writing workflow
needs a separate opt-in design. These are design tasks, not current features.
