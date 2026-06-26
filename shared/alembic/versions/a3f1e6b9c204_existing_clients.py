"""existing_clients

Revision ID: a3f1e6b9c204
Revises: 9c1e2f3a8b7d
Create Date: 2026-05-02 05:20:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3f1e6b9c204"
down_revision: Union[str, Sequence[str], None] = "9c1e2f3a8b7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "existing_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("full_name", sa.String(length=256), nullable=True),
        sa.Column("active_groups", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            server_default="manual_import",
        ),
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
        sa.UniqueConstraint("phone", name="uq_existing_clients_phone"),
    )
    op.create_index(
        "ix_existing_clients_phone", "existing_clients", ["phone"]
    )


def downgrade() -> None:
    op.drop_index("ix_existing_clients_phone", table_name="existing_clients")
    op.drop_table("existing_clients")
