"""add typed target metrics and activity metric values

Revision ID: 6d7e8f9a1b20
Revises: f4b8d2e91a30
"""

from alembic import op
import sqlalchemy as sa

revision = "6d7e8f9a1b20"
down_revision = "f4b8d2e91a30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "targets",
        sa.Column("metric_type", sa.String(length=64), nullable=False, server_default="count"),
    )
    op.add_column(
        "activity_records",
        sa.Column("metric_value", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("activity_records", "metric_value")
    op.drop_column("targets", "metric_type")
