# Privacy and source integrity

PhotoFlow performs local reads of the configured NAS directory. It does not upload
photos or metadata, call a cloud API, collect telemetry, rewrite EXIF, rename files,
copy originals into state, or organize source directories. Network package/image
downloads are part of installation, not indexing or browsing.

## What is retained

SQLite contains relative paths, file sizes and stat signatures, source dimensions
and format, orientation, capture times and offsets, camera make/model, and signed
GPS coordinates where present. It also stores saved album names/date rules, scan
summaries, and a hashed root-path binding. It does not retain raw EXIF JSON, camera
serial numbers, owner/contact fields, face recognition results, or absolute NAS source paths.

Capture times and GPS can be sensitive even without raw EXIF. The unauthenticated
detail endpoint exposes those selected fields to anyone who can access the API.
Saved album names and rules may reveal personal events or date ranges and are
returned by album listing. Album creation persists these definitions only in local state.
Protect the data volume, backups, reverse proxy, and network boundary accordingly.
The thumbnail cache contains recognizable visual data, even though metadata is
removed. Responses request private, nonpersistent client caching. Uvicorn access
logging is disabled by the provided CLI; operator-managed proxy logs can still
contain private request parameters.

## Read-only boundary

Only read flags are used for NAS file descriptors. Internal symlinks are not
followed, and nonregular files are rejected. Pillow writes only to an independent
cache; ExifTool is invoked only with read-only selection flags and stdin. The
application's state path cannot overlap the NAS tree. Docker Compose enforces a
read-only source bind mount and runs without root privileges or extra capabilities.

File reads on a natively writable filesystem can update access times. Use a
read-only host NAS mount or the provided Compose mount when filesystem-level
write protection is required. Source contents and modification times are checked
in synthetic integration tests, including scans of a read-only directory tree.

## Public repository policy

All committed examples are fictional; all test images are generated at runtime in
temporary directories. Do not add family photos, real GPS coordinates, real EXIF
exports, local `.env` files, source listings, production databases, or private logs.
`.gitignore` excludes local state and `.env`; `.dockerignore` allows only build
inputs so local data and Git history are excluded from the image context.

Before sharing a bug report, reproduce with generated images and inspect the
report for paths, filenames, coordinates, timestamps, and private image pixels.
See [SECURITY.md](../SECURITY.md) for vulnerability reporting.
