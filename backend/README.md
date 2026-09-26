# NEXUS Backend — Phase 1

This directory contains only the initial NEXUS backend foundation: FastAPI, Uvicorn, SQLAlchemy 2.x, PostgreSQL configuration, Alembic, settings, and a health check. Domain features are intentionally out of scope.

## Prerequisites

- Python 3.12
- PostgreSQL, if you plan to run database migrations or use the database layer

## Local setup

From this `backend` directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Adjust `DATABASE_URL` in `.env` for your local PostgreSQL instance.

## Run the API

```powershell
uvicorn app.main:app --reload
```

The health endpoint is available at `GET /api/v1/health` and returns HTTP 200 without requiring a database connection.

## Tests

```powershell
pytest
```

The default test suite uses an in-memory session double for user-route coverage and
does not require PostgreSQL. Database schema changes are validated separately with
Alembic against a configured PostgreSQL instance.

## Database migrations

Alembic is configured to read `DATABASE_URL` from the application settings.

```powershell
alembic upgrade head
```

The `User` model stores Argon2id password hashes, and user creation requires a
password. Login, tokens, OAuth, and authorization remain out of scope.
