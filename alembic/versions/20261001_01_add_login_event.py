"""Add login_event table: audit trail of logins/logouts for the admin page.

Revision ID: 20261001_01
Revises: 20260930_03
Create Date: 2026-10-01 18:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_01"
down_revision: Union[str, Sequence[str], None] = "20260930_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "login_event" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "login_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("event", sa.String(length=30), nullable=False),
        sa.Column("user_id", sa.Integer()),
        sa.Column("phone", sa.String(length=20)),
        sa.Column("ip", sa.String(length=64)),
        sa.Column("user_agent", sa.String(length=255)),
        sa.Column("channel", sa.String(length=10)),
        sa.Column("reason", sa.String(length=30)),
    )
    op.create_index("ix_login_event_created_at", "login_event", ["created_at"])
    op.create_index("ix_login_event_event", "login_event", ["event"])
    op.create_index("ix_login_event_user_id", "login_event", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if "login_event" in sa.inspect(bind).get_table_names():
        op.drop_table("login_event")
