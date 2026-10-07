# NEXUS Backend

FastAPI backend for NEXUS, including verified authentication, profile onboarding, planning, execution, and progress APIs.

## Local setup

From this `backend` directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Set `JWT_SECRET_KEY` in `.env` to a long random secret. Keep `.env` local.

### Authentication configuration

For Google sign-in, create a Google OAuth web client and set:

```
GOOGLE_CLIENT_ID=...
```

The frontend receives the same client ID through Vite as `VITE_GOOGLE_CLIENT_ID`.

For local email verification/recovery, NEXUS logs the generated code to the backend terminal when SMTP is not configured. For deployed environments, configure SMTP:

```
SMTP_HOST=...
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM=...
FRONTEND_BASE_URL=https://your-frontend.example
```

Do not use console email delivery in production.

## Run

```powershell
uvicorn app.main:app --reload
```

## Tests

```powershell
pytest
```

## Migrations

```powershell
alembic upgrade head
```

Authentication now supports:

- verified email registration
- Google identity sign-in
- NEXUS username/password creation after identity verification
- password login for verified accounts
- password recovery through verified email
- Argon2id password hashing
- short-lived JWT access tokens and setup tickets
