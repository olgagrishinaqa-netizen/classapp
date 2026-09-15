"""Create the baseline schema and add the user last-login timestamp.

Revision ID: 20260915_01
Revises:
Create Date: 2026-09-15 21:45:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.extensions import db
import app.models  # noqa: F401 -- register model metadata for the baseline schema


revision: str = "20260915_01"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create missing tables and upgrade databases created before Alembic was introduced."""
    bind = op.get_bind()
    db.metadata.create_all(bind=bind)

    inspector = sa.inspect(bind)
    user_columns = {column["name"] for column in inspector.get_columns("user")}
    if "last_login" not in user_columns:
        with op.batch_alter_table("user") as batch_op:
            batch_op.add_column(sa.Column("last_login", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Remove only the column introduced by this revision."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {column["name"] for column in inspector.get_columns("user")}
    if "last_login" in user_columns:
        with op.batch_alter_table("user") as batch_op:
            batch_op.drop_column("last_login")
