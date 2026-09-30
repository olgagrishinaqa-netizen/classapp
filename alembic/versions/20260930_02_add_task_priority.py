"""Add priority column to task for sorting the active quests list.

Revision ID: 20260930_02
Revises: 20260930_01
Create Date: 2026-09-30 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_02"
down_revision: Union[str, Sequence[str], None] = "20260930_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("task")}
    if "priority" not in columns:
        op.add_column(
            "task",
            sa.Column("priority", sa.String(length=10), nullable=False, server_default="medium"),
        )
        with op.batch_alter_table("task") as batch_op:
            batch_op.alter_column("priority", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("task")}
    if "priority" in columns:
        with op.batch_alter_table("task") as batch_op:
            batch_op.drop_column("priority")
