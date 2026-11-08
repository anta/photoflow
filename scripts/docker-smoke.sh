#!/usr/bin/env bash
# Uses only a temporary, generated PNG. Never point this script at real photos.
set -euo pipefail

task_dir=$(mktemp -d)
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
project="photoflow-smoke-$(basename "$task_dir" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9')"
export PHOTOFLOW_NAS_ROOT="$task_dir/nas"
export PHOTOFLOW_PORT=0
compose=(docker compose --file "$repo_root/compose.yaml" --env-file /dev/null --project-name "$project")

cleanup() {
    "${compose[@]}" down --volumes --remove-orphans > /dev/null 2>&1 || true
    chmod u+w "$PHOTOFLOW_NAS_ROOT" 2> /dev/null || true
    rm -rf "$task_dir"
}
trap cleanup EXIT

mkdir "$PHOTOFLOW_NAS_ROOT"
python3 - "$PHOTOFLOW_NAS_ROOT/generated.png" <<'PY'
import pathlib
import struct
import sys
import zlib

def chunk(kind, data):
    return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))

width, height = 96, 64
pixels = (b'\0' + b'\xff\0\0' * width) * height
png = b'\x89PNG\r\n\x1a\n'
png += chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0))
# Minimal TIFF/EXIF with a synthetic DateTimeOriginal in an EXIF sub-IFD.
captured = b'2024:07:15 12:00:00\0'
exif = b'II' + struct.pack('<HI', 42, 8)
exif += struct.pack('<H', 1) + struct.pack('<HHII', 0x8769, 4, 1, 26) + struct.pack('<I', 0)
exif += struct.pack('<H', 1) + struct.pack('<HHII', 0x9003, 2, len(captured), 44)
exif += struct.pack('<I', 0) + captured
png += chunk(b'eXIf', exif)
png += chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b'')
pathlib.Path(sys.argv[1]).write_bytes(png)
PY
chmod 444 "$PHOTOFLOW_NAS_ROOT/generated.png"
chmod 555 "$PHOTOFLOW_NAS_ROOT"
python3 - "$PHOTOFLOW_NAS_ROOT/generated.png" "$task_dir/original.json" <<'PY'
import hashlib
import json
import pathlib
import sys

original = pathlib.Path(sys.argv[1])
snapshot = [hashlib.sha256(original.read_bytes()).hexdigest(), original.stat().st_mtime_ns]
pathlib.Path(sys.argv[2]).write_text(json.dumps(snapshot))
PY

"${compose[@]}" config --quiet
"${compose[@]}" up --detach --no-build --wait --wait-timeout 90
"${compose[@]}" exec -T photoflow photoflow index
"${compose[@]}" exec -T photoflow python -c '
from pathlib import Path
try:
    Path("/photos/must-not-exist").write_bytes(b"test")
except OSError:
    pass
else:
    raise AssertionError("NAS mount must be read-only")
'

address=$("${compose[@]}" port photoflow 8000)
python3 - "http://$address" "$PHOTOFLOW_NAS_ROOT/generated.png" "$task_dir/original.json" <<'PY'
import hashlib
import json
import pathlib
import sys
import urllib.request

base, original, snapshot_path = sys.argv[1:]
with urllib.request.urlopen(base + '/api/v1/photos', timeout=5) as response:
    page = json.load(response)
assert page['total'] == 1, page
photo = page['items'][0]
assert (photo['width'], photo['height']) == (96, 64), photo
assert photo['captured_at'] == '2024-07-15T12:00:00', photo
rule = {
    'version': 1, 'type': 'date_range',
    'start_date': '2024-06-01', 'end_date': '2024-08-31',
}
request = urllib.request.Request(
    base + '/api/v1/albums',
    data=json.dumps({'name': 'Synthetic summer', 'rule': rule}).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST',
)
with urllib.request.urlopen(request, timeout=5) as response:
    assert response.status == 201
    saved = json.load(response)
assert saved['id'].startswith('saved-'), saved
assert saved['label'] == 'Synthetic summer' and saved['rule'] == rule, saved
assert saved['photo_count'] == 1, saved
with urllib.request.urlopen(base + '/api/v1/albums', timeout=5) as response:
    albums = {album['id']: album for album in json.load(response)}
assert albums[saved['id']] == saved, albums
assert albums['undated']['photo_count'] == 0, albums
for album_id in ('all', 'year-2024', 'month-2024-07', saved['id']):
    assert albums[album_id]['photo_count'] == 1, albums
    with urllib.request.urlopen(base + f'/api/v1/albums/{album_id}/photos?limit=1', timeout=5) as response:
        members = json.load(response)
    assert members['total'] == 1 and members['items'][0]['id'] == photo['id'], members
with urllib.request.urlopen(base + photo['thumbnail_url'], timeout=5) as response:
    assert response.headers.get_content_type() == 'image/jpeg'
    assert response.read().startswith(b'\xff\xd8')
original = pathlib.Path(original)
before = json.loads(pathlib.Path(snapshot_path).read_text())
assert [hashlib.sha256(original.read_bytes()).hexdigest(), original.stat().st_mtime_ns] == before
assert [p.name for p in original.parent.iterdir()] == ['generated.png']
print('Docker Compose photo browsing, saved/date albums, thumbnails, and read-only NAS smoke checks passed.')
PY
