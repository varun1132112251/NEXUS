"""add semantic metric type to habits

Revision ID: a1b2c3d4e5f6
Revises: 9a1b2c3d4e51
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "9a1b2c3d4e51"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("habits", sa.Column("metric_type", sa.String(length=64), server_default="count", nullable=False))
    op.execute("""
        UPDATE habits
        SET metric_type = CASE
            WHEN lower(name) LIKE '%dsa%' OR lower(name) LIKE '%problem%' THEN 'problems_solved'
            WHEN lower(name) LIKE '%read%' OR lower(name) LIKE '%reading%' THEN 'pages_read'
            WHEN lower(name) LIKE '%english%' AND lower(name) LIKE '%session%' THEN 'sessions_completed'
            WHEN lower(name) LIKE '%tongue%' THEN 'sessions_completed'
            WHEN lower(name) LIKE '%gate%' THEN 'questions_solved'
            ELSE 'count'
        END
    """)

def downgrade() -> None:
    op.drop_column("habits", "metric_type")
