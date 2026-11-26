"""Add learning_answer table: per-question answers for error analytics and review.

Revision ID: 20261128_01
Revises: 20261127_01
Create Date: 2026-11-28 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20261128_01"
down_revision: Union[str, Sequence[str], None] = "20261127_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "learning_answer" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "learning_answer",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "attempt_id",
            sa.Integer(),
            sa.ForeignKey("learning_attempt.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("subject", sa.String(length=32), nullable=False),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("question_id", sa.String(length=16), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_learning_answer_user_id", "learning_answer", ["user_id"])
    op.create_index(
        "ix_learning_answer_user_question",
        "learning_answer",
        ["user_id", "subject", "topic", "question_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "learning_answer" in sa.inspect(bind).get_table_names():
        op.drop_table("learning_answer")
