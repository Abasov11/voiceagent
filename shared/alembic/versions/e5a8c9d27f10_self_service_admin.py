"""self-service admin: content_blocks + versions + promotions + qualification_categories + agent_settings

Revision ID: e5a8c9d27f10
Revises: a3f1e6b9c204
Create Date: 2026-05-06 04:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "e5a8c9d27f10"
down_revision: Union[str, Sequence[str], None] = "a3f1e6b9c204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "content_blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "format", sa.String(length=16), nullable=False, server_default="text"
        ),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="100"),
        sa.Column(
            "scopes",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[\"voice\"]'::jsonb"),
        ),
        sa.Column(
            "is_system", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("default_body", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("key", name="uq_content_blocks_key"),
    )
    op.create_index(
        "ix_content_blocks_order", "content_blocks", ["order_index"]
    )

    op.create_table(
        "content_block_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "block_id",
            sa.Integer(),
            sa.ForeignKey("content_blocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "format", sa.String(length=16), nullable=False, server_default="text"
        ),
        sa.Column("updated_by", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_content_block_versions_block_id",
        "content_block_versions",
        ["block_id"],
    )

    op.create_table(
        "promotions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "scopes",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[\"voice\", \"whatsapp\"]'::jsonb"),
        ),
        sa.Column("updated_by", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_promotions_active_window",
        "promotions",
        ["is_active", "active_from", "active_to"],
    )

    op.create_table(
        "qualification_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "phrases",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "is_system", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("default_phrases", JSONB(), nullable=True),
        sa.Column("updated_by", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("key", name="uq_qualification_categories_key"),
    )


def downgrade() -> None:
    op.drop_table("qualification_categories")
    op.drop_index("ix_promotions_active_window", table_name="promotions")
    op.drop_table("promotions")
    op.drop_index(
        "ix_content_block_versions_block_id", table_name="content_block_versions"
    )
    op.drop_table("content_block_versions")
    op.drop_index("ix_content_blocks_order", table_name="content_blocks")
    op.drop_table("content_blocks")
    op.drop_table("agent_settings")
