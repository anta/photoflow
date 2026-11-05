"""Create photo index, scan history, and library binding.

Revision ID: 0001
Revises: None
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "library",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("root_fingerprint", sa.String(64), nullable=False),
        sa.CheckConstraint("id = 1", name="single_library"),
    )
    op.create_table(
        "scan_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime),
        sa.Column("status", sa.String(16), nullable=False),
        *(
            sa.Column(name, sa.Integer, nullable=False)
            for name in ("discovered", "added", "updated", "unchanged", "failed", "missing")
        ),
        sa.CheckConstraint("status IN ('running', 'completed', 'failed')", name="scan_status"),
    )
    op.create_table(
        "photos",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("relative_path", sa.Text, nullable=False, unique=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("mtime_ns", sa.BigInteger, nullable=False),
        sa.Column("ctime_ns", sa.BigInteger, nullable=False),
        sa.Column("format", sa.String(16)),
        sa.Column("mime_type", sa.String(64)),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("orientation", sa.Integer),
        sa.Column("captured_at", sa.DateTime),
        sa.Column("captured_at_offset", sa.String(6)),
        sa.Column("camera_make", sa.String(128)),
        sa.Column("camera_model", sa.String(128)),
        sa.Column("latitude", sa.Float),
        sa.Column("longitude", sa.Float),
        sa.Column("indexed_at", sa.DateTime, nullable=False),
        sa.Column("last_seen_scan", sa.String(32), nullable=False),
        sa.Column("is_missing", sa.Boolean, nullable=False),
        sa.Column("index_error", sa.String(32)),
        sa.CheckConstraint("size_bytes >= 0", name="photo_size"),
        sa.CheckConstraint("width IS NULL OR width > 0", name="photo_width"),
        sa.CheckConstraint("height IS NULL OR height > 0", name="photo_height"),
        sa.CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90", name="photo_latitude"
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180", name="photo_longitude"
        ),
        sqlite_autoincrement=True,
    )
    for column in ("captured_at", "last_seen_scan", "is_missing"):
        op.create_index(f"ix_photos_{column}", "photos", [column])


def downgrade():
    op.drop_table("photos")
    op.drop_table("scan_runs")
    op.drop_table("library")
