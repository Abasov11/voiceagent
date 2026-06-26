"""call_summaries: two-track coaching reports ( upgrade)

Revision ID: a7b3c5d8e102
Revises: f2bc4d8e9012
Create Date: 2026-05-11

Добавляет поля report_for_manager / report_for_rop в call_summaries.
Используются новым analyze_dialog (ФВР/STAR/GROW методология).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b3c5d8e102"
down_revision: Union[str, Sequence[str], None] = "f2bc4d8e9012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "call_summaries",
        sa.Column("report_for_manager", sa.Text(), nullable=True),
    )
    op.add_column(
        "call_summaries",
        sa.Column("report_for_rop", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("call_summaries", "report_for_rop")
    op.drop_column("call_summaries", "report_for_manager")
