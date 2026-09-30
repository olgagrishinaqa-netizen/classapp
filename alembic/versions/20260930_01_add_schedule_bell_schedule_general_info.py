"""Add schedule_entry, bell_schedule_entry and general_info tables.

Revision ID: 20260930_01
Revises: 20260928_02
Create Date: 2026-09-30 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_01"
down_revision: Union[str, Sequence[str], None] = "20260928_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the new tables if they are not already present (idempotent —
    see 20260918_01 for why: db.metadata.create_all() may have created them
    on a freshly bootstrapped database already)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "schedule_entry" not in existing_tables:
        op.create_table(
            "schedule_entry",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("day_of_week", sa.Integer(), nullable=False),
            sa.Column("lesson_number", sa.Integer(), nullable=False),
            sa.Column("subject", sa.String(length=120), nullable=False),
            sa.Column("teacher", sa.String(length=120), nullable=True),
            sa.Column("room", sa.String(length=40), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("day_of_week", "lesson_number", name="uq_schedule_day_lesson"),
        )

    if "bell_schedule_entry" not in existing_tables:
        op.create_table(
            "bell_schedule_entry",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("lesson_number", sa.Integer(), nullable=False),
            sa.Column("start_time", sa.Time(), nullable=False),
            sa.Column("end_time", sa.Time(), nullable=False),
            sa.UniqueConstraint("lesson_number", name="uq_bell_schedule_lesson_number"),
        )

    if "general_info" not in existing_tables:
        op.create_table(
            "general_info",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("file_name", sa.String(length=255), nullable=True),
            sa.Column("file_path", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "general_info" in existing_tables:
        op.drop_table("general_info")
    if "bell_schedule_entry" in existing_tables:
        op.drop_table("bell_schedule_entry")
    if "schedule_entry" in existing_tables:
        op.drop_table("schedule_entry")
