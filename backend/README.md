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

## Activity Engine device API

Activity sources let a user link a supported device and send bounded activity signals. Registration, listing, and revocation require a NEXUS access token in `Authorization: Bearer <access-token>`. Event ingestion uses the device credential returned once by registration in the same header. Configure `ACTIVITY_SOURCE_HMAC_KEY` to a random value of at least 32 bytes; the API stores only an HMAC digest and returns the raw device credential only in the registration response.

Supported source types are `windows` and `android`. Source names are unique per user. Revocation immediately prevents further ingestion. The event API accepts only the event categories `app_focus`, `idle`, `active`, and `device_session`, with a timezone-aware `occurred_at` and a small metadata object. Do not send keystrokes, passwords, messages, screenshots, document contents, or arbitrary text.

### Register a device

```http
POST /api/v1/activity-sources
Authorization: Bearer <nexus-access-token>
Content-Type: application/json

{"name":"Work laptop","source_type":"windows"}
```

The `201` response includes source metadata and the device `credential`. Save that credential on the device at registration time; it is not returned by listing or any later request.

### List or revoke devices

```http
GET /api/v1/activity-sources
Authorization: Bearer <nexus-access-token>

DELETE /api/v1/activity-sources/<source-id>
Authorization: Bearer <nexus-access-token>
```

Listing returns only the authenticated user's sources, including revoked entries with `revoked_at`. Revocation returns `204`; unknown or another user's source IDs return `404`.

### Ingest an event

```http
POST /api/v1/activity-sources/events
Authorization: Bearer <device-credential>
Content-Type: application/json

{
  "external_event_id":"win-session-001",
  "event_type":"active",
  "occurred_at":"2026-11-11T10:30:00Z",
  "confidence":0.9,
  "payload":{"duration_seconds":120,"application_category":"development"}
}
```

Successful first submissions return `200` with `duplicate: false`; retrying the same `external_event_id` from the same source returns the original event with `duplicate: true`. Source ownership is derived from the credential; device payloads cannot set `user_id`. Event metadata is limited to 32 scalar fields and 4096 encoded bytes.
