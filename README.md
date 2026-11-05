# PhotoFlow

PhotoFlow is a privacy-first, self-hosted photo organizer for NAS libraries.
This initial MVP indexes photos without modifying their contents or organization.
It is an open-source foundation intended for the CC-CLI v2 program.

## Scope

The MVP covers local configuration, SQLite migrations, recursive scanning,
ExifTool metadata extraction, incremental indexing, a photo browsing REST API,
and Pillow thumbnails. No original photos are copied into this repository.

Virtual smart albums, duplicate detection, physical file organization (including
previews and approval), and a full album management web UI are future work.

## Development

Requires Python 3.12+ and ExifTool. From the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check .
```

Keep original photos outside the repository. Use only generated images in tests;
never commit private photos, GPS records, local databases, or `.env` files.

## License

[MIT](LICENSE).
