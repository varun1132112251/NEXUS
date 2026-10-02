"""link activity records to targets

Revision ID: d14f6c8a2b31
Revises: c92e1f4a7b11
"""

from alembic import op
import sqlalchemy as sa


revision = "d14f6c8a2b31"
down_revision = "c92e1f4a7b11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("activity_records", sa.Column("target_id", sa.Uuid(), nullable=True))
    op.add_column("activity_records", sa.Column("contribution_value", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_activity_records_target_id_targets",
        "activity_records",
        "targets",
        ["target_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_activity_records_target_id", "activity_records", ["target_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_activity_records_target_id", table_name="activity_records")
    op.drop_constraint("fk_activity_records_target_id_targets", "activity_records", type_="foreignkey")
    op.drop_column("activity_records", "contribution_value")
    op.drop_column("activity_records", "target_id")
