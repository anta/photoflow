# REST API

OpenAPI is available at `/openapi.json`, Swagger at `/docs`, and ReDoc at `/redoc`.
The MVP exposes browsing only. There are no HTTP indexing or mutation endpoints.

| Method / path | Response |
| --- | --- |
| `GET /health` | `200 {"status":"ok"}` or `503 {"status":"unavailable"}` |
| `GET /api/v1/photos` | Paginated summary records |
| `GET /api/v1/photos/{id}` | One record with camera and GPS metadata |
| `GET /api/v1/photos/{id}/thumbnail` | Metadata-free JPEG |

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

## Errors and privacy

Unknown IDs return 404. Invalid IDs or query parameters return 422. Thumbnail
requests return 404 for missing sources, 409 for changed or unsuccessfully indexed
sources, 413 for oversized images, 422 for decoding failures, and 503 for storage
failures. Database failures return a generic 503 response. Reindex after a 409.
The health check tests database connectivity and directory presence, not NAS mount
identity or full-library readability.

All responses have `Cache-Control: private, no-store` and
`X-Content-Type-Options: nosniff`. Original files, raw EXIF, absolute NAS paths,
internal fingerprints, and source stat signatures are never returned. Relative
paths, selected GPS data, timestamps, and image pixels are still private data.
