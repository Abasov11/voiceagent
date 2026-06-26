"""call_cost_breakdown

Revision ID: 9c1e2f3a8b7d
Revises: ef6ed8ad2bfa
Create Date: 2026-04-30 04:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "9c1e2f3a8b7d"
down_revision: Union[str, Sequence[str], None] = "ef6ed8ad2bfa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "call_cost_breakdown",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("manager_call_id", sa.Integer(), sa.ForeignKey("manager_calls.id", ondelete="CASCADE"), nullable=True),
        sa.Column("zvonar_call_id", sa.Integer(), sa.ForeignKey("zvonar_calls.id", ondelete="CASCADE"), nullable=True),
        sa.Column("sip_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tts_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stt_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sip_cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tts_cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stt_cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_notes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "(manager_call_id IS NOT NULL) <> (zvonar_call_id IS NOT NULL)",
            name="ck_call_cost_breakdown_xor_call",
        ),
    )
    op.create_index("ix_call_cost_breakdown_manager_call_id", "call_cost_breakdown", ["manager_call_id"])
    op.create_index("ix_call_cost_breakdown_zvonar_call_id",  "call_cost_breakdown", ["zvonar_call_id"])


def downgrade() -> None:
    op.drop_index("ix_call_cost_breakdown_zvonar_call_id",  table_name="call_cost_breakdown")
    op.drop_index("ix_call_cost_breakdown_manager_call_id", table_name="call_cost_breakdown")
    op.drop_table("call_cost_breakdown")
