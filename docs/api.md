# REST API

OpenAPI is available at `/openapi.json`, Swagger at `/docs`, and ReDoc at `/redoc`.
The MVP exposes browsing only. There are no HTTP indexing or mutation endpoints.

| Method / path | Response |
| --- | --- |
| `GET /health` | `200 {"status":"ok"}` or `503 {"status":"unavailable"}` |
| `GET /api/v1/photos` | Paginated summary records |
| `GET /api/v1/photos/{id}` | One record with camera and GPS metadata |
| `GET /api/v1/photos/{id}/thumbnail` | Metadata-free JPEG |
| `GET /api/v1/albums` | Virtual album summaries |
| `GET /api/v1/albums/{album_id}/photos` | Paginated photo summaries for one album |

## Listing

Query parameters:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `limit` | `50` | Page size, 1–200 |
| `offset` | `0` | Nonnegative row offset |
| `query` | absent | Literal substring of the relative path, 1–200 characters |
| `include_missing` | `false` | Include records whose source was not found |

Results sort by relative path, then ID. Search treats `%` and `_` as literal
characters rather than SQL wildcards. SQLite's default text matching is used;
full Unicode case folding is not provided. Offset pagination is not a snapshot:
concurrent indexing can change counts and page positions.

Example with entirely synthetic values:

```json
{
  "items": [{
    "id": 1,
    "relative_path": "generated/example.jpg",
    "size_bytes": 1024,
    "format": "JPEG",
    "mime_type": "image/jpeg",
    "width": 120,
    "height": 80,
    "orientation": 1,
    "captured_at": "2024-02-03T10:11:12",
    "captured_at_offset": "+02:00",
    "indexed_at": "2026-11-05T12:00:00+00:00",
    "is_missing": false,
    "index_error": null,
    "thumbnail_url": "/api/v1/photos/1/thumbnail"
  }],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

Dimensions describe the source raster; orientation is the EXIF orientation value
when available. Thumbnails apply orientation, so their aspect ratio may be swapped.
Capture time is the camera's local wall time with its offset in a separate field.
Unknown offsets and capture times are null. File modification time is not treated
as capture time. `indexed_at` is UTC. The index prefers `DateTimeOriginal`, falling
back to `CreateDate` when the former is missing or invalid.

The detail endpoint adds `camera_make`, `camera_model`, `latitude`, and `longitude`.
Coordinates use signed decimal degrees; absent/invalid values are null. Details
remain available for missing records, with `is_missing=true` and no thumbnail URL.
An `index_error` indicates retained metadata from an earlier successful index and
suppresses the thumbnail URL until a successful retry.

## Virtual albums

`GET /api/v1/albums` returns an array of summaries, for example:

```json
[
  {"id": "all", "label": "All photos", "photo_count": 3},
  {"id": "year-2024", "label": "2024", "photo_count": 2},
  {"id": "month-2024-02", "label": "2024-02", "photo_count": 2},
  {"id": "undated", "label": "Undated", "photo_count": 1}
]
```

IDs describe rules and remain stable as counts change. The list starts with `all`,
then years newest first, each followed by its months newest first, and ends with
`undated`. Year/month albums appear only when nonempty. All photos and Undated
are always listed, including for an empty library. The summary list is unpaginated.
Year and month labels use fixed ISO calendar notation, independent of server locale.

`GET /api/v1/albums/month-2024-02/photos?limit=20&offset=0` returns the same
`PhotoPage` shape as photo listing. Only `limit` (1–200, default 50) and `offset`
(nonnegative, default 0) are supported. Results sort by relative path, then ID;
`total` counts all eligible album members even beyond the requested page. An offset
past the last member returns an empty page with that total. Invalid IDs and empty
year/month albums return `404 {"detail":"Album not found"}`. Invalid pagination
parameters return 422.

Every generated album, including `all` and `undated`, excludes missing photos and
records with a non-null `index_error`. There is no inclusion override. Ordinary
`/photos` browsing retains its existing behavior: errors remain visible, and
missing records can be included explicitly.

Grouping uses the stored camera calendar date without applying `captured_at_offset`,
converting to UTC, or consulting the server timezone. For example, a capture at
`2024-01-01T00:00:00` with offset `+14:00` belongs to `year-2024` and `month-2024-01`.
Absent or unusable capture dates belong to `undated`; filesystem timestamps are
never used as a substitute. A photo may appear in multiple albums with the same ID.

Membership is calculated from the current index without file copies or stored
membership rows. Reindexing date changes, new files, missing originals, and successful
retries update subsequent responses automatically. Scanning remains manual.
Counts and page positions can change during concurrent indexing; separate requests
do not share a snapshot. Album responses use the same privacy headers as photos.

## Errors and privacy

Unknown photo IDs return 404. Invalid photo IDs or query parameters return 422. Thumbnail
requests return 404 for missing sources, 409 for changed or unsuccessfully indexed
sources, 413 for oversized images, 422 for decoding failures, and 503 for storage
failures. Database failures return a generic 503 response. Reindex after a 409.
The health check tests database connectivity and directory presence, not NAS mount
identity or full-library readability.

All responses have `Cache-Control: private, no-store` and
`X-Content-Type-Options: nosniff`. Original files, raw EXIF, absolute NAS paths,
internal fingerprints, and source stat signatures are never returned. Relative
paths, selected GPS data, timestamps, and image pixels are still private data.
