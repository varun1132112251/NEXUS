"""normalize target metric types for existing targets

Revision ID: a7c2e9f14b60
Revises: 8f9a1b2c3d40
Create Date: 2026-10-04
"""
from alembic import op

revision = "a7c2e9f14b60"
down_revision = "8f9a1b2c3d40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE targets
        SET metric_type = CASE
            WHEN lower(title) LIKE '%dsa%' OR lower(title) LIKE '%problem%' THEN 'problems_solved'
            WHEN lower(title) LIKE '%book%' AND (lower(title) LIKE '%read%' OR lower(title) LIKE '%reading%') THEN 'books_completed'
            WHEN lower(title) LIKE '%english%' AND lower(title) LIKE '%session%' THEN 'sessions_completed'
            WHEN lower(title) LIKE '%gate%' AND lower(title) LIKE '%revision%' THEN 'topics_revised'
            WHEN lower(title) LIKE '%gate%' AND lower(title) LIKE '%question%' THEN 'questions_solved'
            WHEN lower(title) LIKE '%nexus%' AND (lower(title) LIKE '%complete%' OR lower(title) LIKE '%v1%') THEN 'milestones_completed'
            ELSE metric_type
        END
        WHERE metric_type = 'count'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE targets
        SET metric_type = 'count'
        WHERE metric_type IN (
            'problems_solved',
            'books_completed',
            'sessions_completed',
            'topics_revised',
            'questions_solved',
            'milestones_completed'
        )
    """)
