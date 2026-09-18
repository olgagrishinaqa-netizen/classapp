"""Add the students table for class roster management.

Revision ID: 20260918_01
Revises: 20260915_01
Create Date: 2026-09-18 17:45:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260918_01"
down_revision: Union[str, Sequence[str], None] = "20260915_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the 'students' table if it does not already exist.

    The project's baseline migration (20260915_01) calls
    ``db.metadata.create_all()`` against the *current* models, so on a
    brand-new database the table may already be present. This guard keeps
    the migration idempotent for both freshly bootstrapped and
    already-baselined (pre-existing) Patroni-backed PostgreSQL clusters.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "students" in inspector.get_table_names():
        return

    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_name", sa.String(length=64), nullable=False),
        sa.Column("first_name", sa.String(length=64), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(op.f("ix_students_last_name"), "students", ["last_name"])
    op.create_index(op.f("ix_students_first_name"), "students", ["first_name"])


def downgrade() -> None:
    """Drop the 'students' table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "students" not in inspector.get_table_names():
        return

    op.drop_index(op.f("ix_students_first_name"), table_name="students")
    op.drop_index(op.f("ix_students_last_name"), table_name="students")
    op.drop_table("students")
