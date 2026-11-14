"""Upgrade and rollback safeguards for the planner lifecycle migration."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


POSTGRES_TEST_URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_TEST_URL, reason="requires a dedicated disposable PostgreSQL database")


def test_planner_migration_backfills_history_and_protects_downgrade(monkeypatch):
    admin = create_engine(POSTGRES_TEST_URL)
    schema = f"planner_migration_{uuid4().hex}"
    engine = None
    try:
        with admin.begin() as connection:
            assert connection.dialect.name == "postgresql"
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')

        isolated_url = make_url(POSTGRES_TEST_URL).update_query_dict({"options": f"-csearch_path={schema}"})
        from app.core.config import settings

        monkeypatch.setattr(settings, "database_url", isolated_url.render_as_string(hide_password=False))
        backend_dir = Path(__file__).resolve().parents[1]
        config = Config(str(backend_dir / "alembic.ini"))
        command.upgrade(config, "j2c3d4e5f6a1")
        engine = create_engine(isolated_url)

        user_id, task_id, schedule_id = uuid4(), uuid4(), uuid4()
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO users(id, username, email, password_hash) VALUES (:id, :name, :email, '')"), {
                "id": user_id, "name": f"planner-{user_id.hex}", "email": f"{user_id.hex}@example.test",
            })
            connection.execute(text("INSERT INTO tasks(id, user_id, title, status, priority) VALUES (:id, :user, 'existing task', 'planned', 3)"), {"id": task_id, "user": user_id})
            connection.execute(text("""
                INSERT INTO schedule_items(id, user_id, title, scheduled_date, start_at, end_at, status, priority)
                VALUES (:id, :user, 'existing schedule', DATE '2026-11-18', TIMESTAMPTZ '2026-11-18 09:00:00+00', TIMESTAMPTZ '2026-11-18 10:00:00+00', 'planned', 3)
            """), {"id": schedule_id, "user": user_id})

        command.upgrade(config, "k3d4e5f6a7b8")
        command.upgrade(config, "k6a7b8c9d0e1")
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT count(*) FROM task_status_events WHERE task_id=:id AND event_kind='baseline'"), {"id": task_id}) == 1
            assert connection.scalar(text("SELECT count(*) FROM schedule_status_events WHERE schedule_item_id=:id AND event_kind='baseline'"), {"id": schedule_id}) == 1
            connection.execute(text("UPDATE tasks SET status='in_progress' WHERE id=:id"), {"id": task_id})
            connection.execute(text("UPDATE schedule_items SET status='partial' WHERE id=:id"), {"id": schedule_id})
            assert connection.scalar(text("SELECT count(*) FROM task_status_events WHERE task_id=:id AND event_kind='changed' AND previous_status='planned' AND new_status='in_progress'"), {"id": task_id}) == 1
            assert connection.scalar(text("SELECT count(*) FROM schedule_status_events WHERE schedule_item_id=:id AND event_kind='changed' AND previous_status='planned' AND new_status='partial'"), {"id": schedule_id}) == 1

        with pytest.raises(RuntimeError, match="user-created status history"):
            command.downgrade(config, "j2c3d4e5f6a1")
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin.dispose()


def test_planner_migration_can_downgrade_when_only_legacy_rows_exist(monkeypatch):
    admin = create_engine(POSTGRES_TEST_URL)
    schema = f"planner_migration_safe_{uuid4().hex}"
    engine = None
    try:
        with admin.begin() as connection:
            assert connection.dialect.name == "postgresql"
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        isolated_url = make_url(POSTGRES_TEST_URL).update_query_dict({"options": f"-csearch_path={schema}"})
        from app.core.config import settings

        monkeypatch.setattr(settings, "database_url", isolated_url.render_as_string(hide_password=False))
        backend_dir = Path(__file__).resolve().parents[1]
        config = Config(str(backend_dir / "alembic.ini"))
        command.upgrade(config, "j2c3d4e5f6a1")
        engine = create_engine(isolated_url)
        user_id, task_id, schedule_id = uuid4(), uuid4(), uuid4()
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO users(id, username, email, password_hash) VALUES (:id, :name, :email, '')"), {
                "id": user_id, "name": f"planner-safe-{user_id.hex}", "email": f"{user_id.hex}@example.test",
            })
            connection.execute(text("INSERT INTO tasks(id, user_id, title, status, priority) VALUES (:id, :user, 'legacy task', 'planned', 3)"), {"id": task_id, "user": user_id})
            connection.execute(text("""
                INSERT INTO schedule_items(id, user_id, title, scheduled_date, start_at, end_at, status, priority)
                VALUES (:id, :user, 'legacy schedule', DATE '2026-11-18', TIMESTAMPTZ '2026-11-18 09:00:00+00', TIMESTAMPTZ '2026-11-18 10:00:00+00', 'planned', 3)
            """), {"id": schedule_id, "user": user_id})
        command.upgrade(config, "k3d4e5f6a7b8")
        command.upgrade(config, "k6a7b8c9d0e1")
        command.downgrade(config, "k5f6a7b8c9d0")
        command.downgrade(config, "k4e5f6a7b8c9")
        command.downgrade(config, "k3d4e5f6a7b8")
        command.downgrade(config, "j2c3d4e5f6a1")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT status FROM tasks WHERE id=:id"), {"id": task_id}) == "planned"
            assert connection.scalar(text("SELECT status FROM schedule_items WHERE id=:id"), {"id": schedule_id}) == "planned"
            assert connection.scalar(text("SELECT to_regclass('task_status_events')")) is None
            assert connection.scalar(text("SELECT to_regclass('schedule_status_events')")) is None
            assert connection.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_schema=:schema AND column_name='deleted_at' AND table_name IN ('tasks', 'schedule_items')"), {"schema": schema}) == 0
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin.dispose()


def test_task_goal_migration_refuses_to_drop_live_goal_links(monkeypatch):
    admin = create_engine(POSTGRES_TEST_URL)
    schema = f"planner_task_goal_downgrade_{uuid4().hex}"
    engine = None
    try:
        with admin.begin() as connection:
            assert connection.dialect.name == "postgresql"
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        isolated_url = make_url(POSTGRES_TEST_URL).update_query_dict({"options": f"-csearch_path={schema}"})
        from app.core.config import settings

        monkeypatch.setattr(settings, "database_url", isolated_url.render_as_string(hide_password=False))
        backend_dir = Path(__file__).resolve().parents[1]
        config = Config(str(backend_dir / "alembic.ini"))
        command.upgrade(config, "head")
        engine = create_engine(isolated_url)
        user_id, ambition_id, goal_id, task_id = uuid4(), uuid4(), uuid4(), uuid4()
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO users(id, username, email, password_hash) VALUES (:id, :name, :email, '')"), {
                "id": user_id, "name": f"planner-goal-{user_id.hex}", "email": f"{user_id.hex}@example.test",
            })
            connection.execute(text("INSERT INTO ambitions(id, user_id, title, category) VALUES (:id, :user, 'Learn', 'education')"), {"id": ambition_id, "user": user_id})
            connection.execute(text("INSERT INTO ambition_goals(id, user_id, ambition_id, title) VALUES (:id, :user, :ambition, 'Finish course')"), {"id": goal_id, "user": user_id, "ambition": ambition_id})
            connection.execute(text("INSERT INTO tasks(id, user_id, title, ambition_goal_id, status, priority) VALUES (:id, :user, 'Study', :goal, 'planned', 3)"), {"id": task_id, "user": user_id, "goal": goal_id})
        with pytest.raises(RuntimeError, match="task goal association"):
            command.downgrade(config, "k3d4e5f6a7b8")
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin.dispose()
