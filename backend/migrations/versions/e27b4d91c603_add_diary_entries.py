"""add diary entries

Revision ID: e27b4d91c603
Revises: d14f6c8a2b31
"""

from alembic import op
import sqlalchemy as sa

revision = "e27b4d91c603"
down_revision = "d14f6c8a2b31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "diary_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("accomplishments", sa.Text(), nullable=True),
        sa.Column("what_went_badly", sa.Text(), nullable=True),
        sa.Column("learned", sa.Text(), nullable=True),
        sa.Column("feelings", sa.Text(), nullable=True),
        sa.Column("distractions", sa.Text(), nullable=True),
        sa.Column("tomorrow_changes", sa.Text(), nullable=True),
        sa.Column("free_writing", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "entry_date", name="uq_diary_entries_user_date"),
    )
    op.create_index("ix_diary_entries_user_id", "diary_entries", ["user_id"])
    op.create_index("ix_diary_entries_entry_date", "diary_entries", ["entry_date"])


def downgrade() -> None:
    op.drop_index("ix_diary_entries_entry_date", table_name="diary_entries")
    op.drop_index("ix_diary_entries_user_id", table_name="diary_entries")
    op.drop_table("diary_entries")
