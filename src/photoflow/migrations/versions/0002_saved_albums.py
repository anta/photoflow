"""Persist named date-range album definitions without photo memberships.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "saved_albums",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("rule_version", sa.Integer, nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 128", name="album_name_length"),
        sa.CheckConstraint("rule_version = 1", name="album_rule_version"),
        sa.CheckConstraint("start_date <= end_date", name="album_date_range"),
        sqlite_autoincrement=True,
    )


def downgrade():
    op.drop_table("saved_albums")
