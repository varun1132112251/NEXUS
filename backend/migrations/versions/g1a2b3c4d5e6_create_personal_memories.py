"""create structured personal memories

Revision ID: g1a2b3c4d5e6
Revises: f1a2b3c4d5e6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "personal_memories",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.String(length=24), server_default="user_stated", nullable=False),
        sa.Column("confidence", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("importance", sa.Integer(), server_default="3", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(
            "category IN ('identity', 'goal_context', 'preference', 'constraint', 'commitment_context', 'experience', 'behavior_pattern')",
            name="ck_personal_memories_category",
        ),
        sa.CheckConstraint(
            "source_kind IN ('user_stated', 'system_observed', 'agent_inferred', 'imported')",
            name="ck_personal_memories_source_kind",
        ),
        sa.CheckConstraint("status IN ('active', 'superseded', 'archived')", name="ck_personal_memories_status"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_personal_memories_confidence"),
        sa.CheckConstraint("importance >= 1 AND importance <= 5", name="ck_personal_memories_importance"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["personal_memories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_memories_user_id", "personal_memories", ["user_id"], unique=False)
    op.create_index(
        "ix_personal_memories_user_status_category",
        "personal_memories",
        ["user_id", "status", "category"],
        unique=False,
    )
    op.create_index(
        "ix_personal_memories_user_updated",
        "personal_memories",
        ["user_id", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_personal_memories_user_updated", table_name="personal_memories")
    op.drop_index("ix_personal_memories_user_status_category", table_name="personal_memories")
    op.drop_index("ix_personal_memories_user_id", table_name="personal_memories")
    op.drop_table("personal_memories")
