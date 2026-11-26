"""Add learning_attempt table: results of student tests by topic.

Revision ID: 20261126_01
Revises: 20261001_01
Create Date: 2026-11-26 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20261126_01"
down_revision: Union[str, Sequence[str], None] = "20261001_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "learning_attempt" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "learning_attempt",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("subject", sa.String(length=32), nullable=False),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_learning_attempt_user_id", "learning_attempt", ["user_id"])
    op.create_index(
        "ix_learning_attempt_user_topic", "learning_attempt", ["user_id", "subject", "topic"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "learning_attempt" in sa.inspect(bind).get_table_names():
        op.drop_table("learning_attempt")
