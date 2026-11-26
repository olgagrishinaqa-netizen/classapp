"""Add user.parent_id: the parent who sees a student's test results.

Revision ID: 20261127_01
Revises: 20261126_01
Create Date: 2026-11-27 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20261127_01"
down_revision: Union[str, Sequence[str], None] = "20261126_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("user")}
    if "parent_id" in columns:
        return
    with op.batch_alter_table("user") as batch:
        batch.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_user_parent_id_user", "user", ["parent_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("ix_user_parent_id", ["parent_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("user")}
    if "parent_id" not in columns:
        return
    # Имя FK зависит от того, кто создал столбец (эта миграция или базовая схема), поэтому берём его из БД.
    fk_names = [
        fk["name"]
        for fk in inspector.get_foreign_keys("user")
        if fk.get("name") and fk["constrained_columns"] == ["parent_id"]
    ]
    index_names = [
        i["name"] for i in inspector.get_indexes("user") if i["column_names"] == ["parent_id"]
    ]
    with op.batch_alter_table("user") as batch:
        for name in index_names:
            batch.drop_index(name)
        if (
            bind.dialect.name != "sqlite"
        ):  # SQLite пересоздаёт таблицу и теряет FK вместе со столбцом
            for name in fk_names:
                batch.drop_constraint(name, type_="foreignkey")
        batch.drop_column("parent_id")
