"""Attribute payments to a student instead of a registered parent account.

Revision ID: 20260928_01
Revises: 20260918_01
Create Date: 2026-09-28 18:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_01"
down_revision: Union[str, Sequence[str], None] = "20260918_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add payment.student_id (nullable FK to students) and relax
    payment.user_id to nullable, since new payments no longer require a
    registered parent account — only an entry in the class roster.

    Guarded for idempotency: the baseline migration's create_all() may
    already reflect the current model on a freshly bootstrapped database.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    payment_columns = {column["name"]: column for column in inspector.get_columns("payment")}

    with op.batch_alter_table("payment") as batch_op:
        if "student_id" not in payment_columns:
            batch_op.add_column(sa.Column("student_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_payment_student_id_students", "students", ["student_id"], ["id"]
            )
            batch_op.create_index(
                op.f("ix_payment_student_id"), ["student_id"], unique=False
            )
        if payment_columns.get("user_id") is not None and not payment_columns["user_id"]["nullable"]:
            batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    """Drop student_id and restore user_id NOT NULL."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    payment_columns = {column["name"] for column in inspector.get_columns("payment")}
    # Имена берём из самой БД: на базе, созданной через create_all() (baseline-миграция),
    # внешний ключ называется иначе, чем в upgrade(), и откат по «зашитому» имени падал.
    fk_names = [
        fk["name"]
        for fk in inspector.get_foreign_keys("payment")
        if fk.get("constrained_columns") == ["student_id"] and fk.get("name")
    ]
    index_names = {index["name"] for index in inspector.get_indexes("payment")}

    with op.batch_alter_table("payment") as batch_op:
        if "student_id" in payment_columns:
            if "ix_payment_student_id" in index_names:
                batch_op.drop_index(op.f("ix_payment_student_id"))
            for fk_name in fk_names:
                batch_op.drop_constraint(fk_name, type_="foreignkey")
            batch_op.drop_column("student_id")
        batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
