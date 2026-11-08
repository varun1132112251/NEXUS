# NEXUS Personal Memory Foundation — V1.2

## Purpose

The personal memory layer stores durable context explicitly associated with one authenticated user. It is separate from the execution ledger and planning records.

## Existing records remain the source of truth

Do not duplicate these domains in personal memory:

- User identity and authentication: `users`
- Profile and availability/preferences already captured by onboarding: `user_profiles`
- Goals currently represented by monthly targets: `targets`
- Planned work: `tasks`, `schedules`, and `routine_templates`
- Actual measured work: `time_sessions` and `activity_records`
- Daily reflection: `diary_entries`

Personal memories hold durable context that helps NEXUS interpret those records: identity context, goal context, preferences, constraints, commitment context, experiences, and behavioural patterns.

A commitment or completed action must not be fabricated from a memory row. Planned work stays in the planning domain; actual execution stays in activity/time records.

## Memory record

Each memory is scoped to exactly one user and contains:

- Category, title, and content
- Provenance: user stated, system observed, agent inferred, or imported
- Confidence from 0.0 to 1.0
- Importance from 1 to 5
- Lifecycle status: active, superseded, or archived
- Optional source reference, JSON details, expiry, and replacement link
- Created and updated timestamps

The initial API only accepts user-stated memories and assigns confidence 1.0. System-observed and agent-inferred memories are reserved for trusted internal services with evidence and evaluation; clients cannot claim those provenance types.

## API

All routes require the authenticated user:

- `POST /api/v1/memory` — create a user-stated memory
- `GET /api/v1/memory` — list memories; defaults to active and non-expired
- `GET /api/v1/memory/{id}` — read one active or superseded memory owned by the user
- `PATCH /api/v1/memory/{id}` — update an active memory
- `POST /api/v1/memory/{id}/archive` — archive an active memory
- `DELETE /api/v1/memory/{id}` — permanently delete an owned memory

List filters support category, lifecycle status, text search, and optionally expired records.

When a replacement is created, it may reference an existing active memory using `supersedes_id`. The old memory becomes superseded in the same transaction. Replacement must be owned by the same user and have the same category.

## Safety and integrity

- Every read, update, archive, replacement, and delete is scoped by authenticated user ID.
- Database checks constrain category, provenance, lifecycle status, confidence, and importance.
- Expiry timestamps must include timezone information.
- Memories do not automatically expire or get superseded based on model guesses.
- No vector embeddings, semantic search, autonomous inference, or LLM calls are part of this slice.
- Sensitive information should not be added to memory by inference without explicit user approval and a clear need.

## Next phases

1. Validate this persistence/API slice against PostgreSQL and automated tests.
2. Add explicit evidence references for system-observed memories.
3. Add a review/confirmation workflow before agent-inferred memories become active.
4. Connect memory retrieval to profile, goals, schedule, diary, and execution context without copying source records.
5. Add semantic retrieval only after measured need; use embeddings as an index, never as the canonical memory store.
