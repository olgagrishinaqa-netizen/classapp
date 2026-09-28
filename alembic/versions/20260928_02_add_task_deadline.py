"""Add an optional deadline to tasks.

Revision ID: 20260928_02
Revises: 20260928_01
Create Date: 2026-09-28 19:30:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_02"
down_revision: Union[str, Sequence[str], None] = "20260928_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add task.deadline (nullable date), guarded for a baseline database
    whose create_all() already reflects the current model."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    task_columns = {column["name"] for column in inspector.get_columns("task")}

    if "deadline" not in task_columns:
        op.add_column("task", sa.Column("deadline", sa.Date(), nullable=True))


def downgrade() -> None:
    """Drop task.deadline."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    task_columns = {column["name"] for column in inspector.get_columns("task")}
    if "deadline" in task_columns:
        op.drop_column("task", "deadline")
