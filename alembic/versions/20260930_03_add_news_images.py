"""Add news_image table for multiple images per news item.

Existing single images (news.image_name / news.image_path) are copied into
news_image and the old columns are dropped.

Revision ID: 20260930_03
Revises: 20260930_02
Create Date: 2026-09-30 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_03"
down_revision: Union[str, Sequence[str], None] = "20260930_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "news_image" not in inspector.get_table_names():
        op.create_table(
            "news_image",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("news_id", sa.Integer(), sa.ForeignKey("news.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=255)),
            sa.Column("path", sa.String(length=255), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index("ix_news_image_news_id", "news_image", ["news_id"])

    columns = {column["name"] for column in inspector.get_columns("news")}
    if "image_path" in columns:
        op.execute(
            "INSERT INTO news_image (news_id, name, path, position) "
            "SELECT id, image_name, image_path, 0 FROM news WHERE image_path IS NOT NULL"
        )
        with op.batch_alter_table("news") as batch_op:
            batch_op.drop_column("image_path")
            if "image_name" in columns:
                batch_op.drop_column("image_name")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("news")}
    if "image_path" not in columns:
        with op.batch_alter_table("news") as batch_op:
            batch_op.add_column(sa.Column("image_name", sa.String(length=255)))
            batch_op.add_column(sa.Column("image_path", sa.String(length=255)))
        op.execute(
            "UPDATE news SET image_path = (SELECT path FROM news_image WHERE news_image.news_id = news.id "
            "ORDER BY position, id LIMIT 1), "
            "image_name = (SELECT name FROM news_image WHERE news_image.news_id = news.id "
            "ORDER BY position, id LIMIT 1)"
        )
    if "news_image" in inspector.get_table_names():
        op.drop_index("ix_news_image_news_id", table_name="news_image")
        op.drop_table("news_image")
