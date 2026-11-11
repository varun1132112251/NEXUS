"""Alembic migration checks against an explicitly isolated PostgreSQL database."""

import os
from pathlib import Path
from uuid import uuid4
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


POSTGRES_TEST_URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_TEST_URL,
    reason="requires a dedicated disposable PostgreSQL database",
)


def test_activity_migration_clean_upgrade_and_downgrade(monkeypatch):
    """Run the actual revision chain in a disposable per-test schema."""
    admin = create_engine(POSTGRES_TEST_URL)
    schema = f"activity_migration_test_{uuid4().hex}"
    backend_dir = Path(__file__).resolve().parents[1]
    verify_engine = None
    try:
        with admin.begin() as connection:
            assert connection.dialect.name == "postgresql"
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')

        isolated_url = make_url(POSTGRES_TEST_URL).update_query_dict(
            {"options": f"-csearch_path={schema}"}
        )
        from app.core.config import settings

        monkeypatch.setattr(
            settings,
            "database_url",
            isolated_url.render_as_string(hide_password=False),
        )
        config = Config(str(backend_dir / "alembic.ini"))
        command.upgrade(config, "g1a2b3c4d5e6")
        command.upgrade(config, "h7a8b9c0d1e2")

        verify_engine = create_engine(isolated_url)
        with verify_engine.connect() as connection:
            assert connection.scalar(text("SELECT to_regclass('activity_sources')")) is not None
            assert connection.scalar(text("SELECT to_regclass('activity_events')")) is not None
            trigger_count = connection.scalar(text("""
                SELECT count(*) FROM pg_trigger tr
                JOIN pg_class tbl ON tbl.oid = tr.tgrelid
                JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
                WHERE ns.nspname = current_schema()
                  AND NOT tr.tgisinternal AND tr.tgname IN (
                  'trg_activity_time_allocation_insert',
                  'trg_activity_time_allocation_update',
                  'trg_activity_time_allocation_delete',
                  'trg_activity_session_duration_allocation_limit',
                  'trg_activity_contribution_target_type',
                  'trg_target_metric_type_activity_contributions',
                  'trg_activity_corrections_immutable'
                )
            """))
            assert trigger_count == 7

        user_id, target_id = uuid4(), uuid4()
        session_to_delete, retained_session = uuid4(), uuid4()
        with verify_engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO users (id, username, email, password_hash)
                VALUES (:id, :username, :email, '')
            """), {
                "id": user_id,
                "username": f"migration-{user_id.hex}",
                "email": f"{user_id.hex}@example.test",
            })
            connection.execute(text("""
                INSERT INTO targets (id, user_id, title, month, metric_type)
                VALUES (:id, :user_id, 'migration time target', :month, 'time')
            """), {
                "id": target_id,
                "user_id": user_id,
                "month": datetime.now(UTC).date().replace(day=1),
            })
            for session_id in (session_to_delete, retained_session):
                connection.execute(text("""
                    INSERT INTO activity_sessions (
                      id, user_id, title, started_at, ended_at, duration_seconds, status
                    ) VALUES (
                      :id, :user_id, 'migration test', CURRENT_TIMESTAMP - interval '10 minutes',
                      CURRENT_TIMESTAMP, 100, 'confirmed'
                    )
                """), {"id": session_id, "user_id": user_id})
            for session_id, contribution_id, value in (
                (session_to_delete, uuid4(), 40),
                (retained_session, uuid4(), 30),
            ):
                connection.execute(text("""
                    INSERT INTO activity_goal_contributions (
                      id, user_id, activity_session_id, target_id,
                      contribution_type, contribution_value, unit
                    ) VALUES (
                      :id, :user_id, :session_id, :target_id, 'time', :value, 'seconds'
                    )
                """), {
                    "id": contribution_id,
                    "user_id": user_id,
                    "session_id": session_id,
                    "target_id": target_id,
                    "value": value,
                })
            connection.execute(
                text("DELETE FROM activity_sessions WHERE id = :id"),
                {"id": session_to_delete},
            )
            assert connection.scalar(text(
                "SELECT count(*) FROM activity_sessions WHERE id = :id"
            ), {"id": session_to_delete}) == 0
            assert connection.scalar(text(
                "SELECT count(*) FROM activity_goal_contributions WHERE activity_session_id = :id"
            ), {"id": session_to_delete}) == 0
            assert connection.scalar(text(
                "SELECT count(*) FROM activity_sessions WHERE id = :id"
            ), {"id": retained_session}) == 1
            assert connection.scalar(text(
                "SELECT count(*) FROM activity_goal_contributions WHERE activity_session_id = :id"
            ), {"id": retained_session}) == 1

        command.downgrade(config, "g1a2b3c4d5e6")
        with verify_engine.connect() as connection:
            assert connection.scalar(text("SELECT to_regclass('activity_sources')")) is None
            assert connection.scalar(text("SELECT to_regclass('time_sessions')")) is not None
            restored_fks = connection.scalar(text("""
                SELECT count(*) FROM pg_constraint con
                JOIN pg_class tbl ON tbl.oid = con.conrelid
                JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
                WHERE ns.nspname = current_schema()
                  AND con.conname IN (
                  'fk_time_sessions_target_id_targets',
                  'time_sessions_task_id_fkey',
                  'time_sessions_habit_id_fkey',
                  'time_sessions_project_id_fkey',
                  'time_sessions_schedule_item_id_fkey'
                ) AND con.contype = 'f'
            """))
            assert restored_fks == 5
    finally:
        if verify_engine is not None:
            verify_engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin.dispose()
