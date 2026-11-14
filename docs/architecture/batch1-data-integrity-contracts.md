# NEXUS Batch 1 — Data Integrity and Product Contracts

Status: source audit and contract specification. This document does not change database behavior.

## 1. Data model responsibilities

| Model | Existing responsibility | Existing safeguards | Missing contract / risk |
| --- | --- | --- | --- |
| `ActivitySource` | User-owned device/source registration and revocation | Credential HMAC digest only; unique user/name; composite ownership FK for events; revoked sources are rejected | No lifecycle or retention policy for revoked metadata; user-facing export/delete policy is undefined |
| `ActivityEvent` | Immutable-by-convention raw device observation | `(source_id, external_event_id)` unique; same-user source FK; confidence check; source and user timestamp indexes; strict API payload | No model-level update/delete immutability or retention policy; no review link to an ActivitySession |
| `ActivitySession` | Reviewable interpreted activity, separate from stopwatch `TimeSession` | Draft/confirmed/corrected/discarded states; timing/status/confidence checks; user-scoped links; optional unique `time_session_id` | No source-event relationship; no explicit manual/observed provenance; no review API; correction rows can prevent session deletion |
| `ActivityGoalContribution` | Typed metric, milestone, and time contribution from an ActivitySession to a monthly Target | User-scoped FKs; typed units/checks; target metric trigger; PostgreSQL trigger serializes writes and caps summed time at session duration | No goal entity beyond Target; allocation/metric update and reversal semantics are not exposed as a complete API; direct writes are protected for time capacity but service-level eligibility still matters |
| `ActivityCorrection` | Before/after audit record for one session field | ORM immutability; PostgreSQL trigger rejects update/delete; session/user FK uses RESTRICT | No correction service/API; correction history is not independently exportable; RESTRICT complicates account/session deletion |
| `TimeSession` | Stopwatch session and direct links to schedule/task/habit/project/target | One running session per user partial unique index; timing/status check; composite owner FKs | No pause/resume, source/provenance type, manual entry workflow, or correction/split/merge contract |
| `ActivityRecord` | User-entered measured execution evidence, optionally reviewing a TimeSession | One record per time session; transactional target increment; field validation and owner lookup in API | Not linked to ActivitySession/correction ledger; target increment history/reversal is not modeled as an immutable contribution |
| `Target` | Period-specific measurable target (normally monthly) | User ownership; composite unique key supports scoped references; activity contribution trigger protects metric type | Not a durable ambition or lifetime goal; no milestone hierarchy or target history snapshot |
| `Task` | Planned work item linked to project and/or target | User ownership and scoped parent links | No dependency graph, transition policy, or execution history of state changes |
| `ScheduleItem` | Dated planned block and execution status | Time-range check; user-scoped links; API validates same scheduled date and end after start | No database overlap constraint; timezone contract needs a defined user timezone; planned-vs-actual review is partial |
| `RoutineTemplate` | Recurring local-time template used to generate ScheduleItems | User ownership; links to planning records | No explicit timezone, overlap, or historical template-version policy |
| `PersonalMemory` | Durable user-scoped context with provenance, confidence, importance and lifecycle | Category/status/provenance/value checks; expiry timezone validation; replacement ownership/category validation in API | API supports CRUD/archive but no export or broader retention/deletion policy; UI absent |
| `DiaryEntry` | One editable reflection per user and date | Unique `(user_id, entry_date)`; API ownership checks | No explicit export/retention contract; account deletion is not implemented as a user workflow |

### Overlap rules

- `ActivityEvent` is raw observed evidence; `ActivitySession` is a user-reviewable interpretation; `TimeSession` is a stopwatch record; `ActivityRecord` is measured execution evidence. Keep these distinct.
- An ActivitySession may refer to a stopwatch session, but that optional FK does not establish raw observation provenance.
- Target progress currently has more than one path: ActivityRecord can increment `Target.current_value`, while ActivityGoalContribution records typed contributions. A future contract must choose one canonical ledger for each target metric and ensure aggregate updates are atomic and reversible; do not count both paths for the same evidence.
- Monthly Target is not a lifetime ambition. Do not overload Target with ambition hierarchy or permanent identity.

## 2. Time integrity specification

1. **Observed is not confirmed.** Persist collector observations as ActivityEvents. They do not become confirmed time or progress until an explicit review action creates/confirms an ActivitySession.
2. **Evidence is retained.** Every observed-derived ActivitySession must reference one or more ActivityEvents. Prefer a join table such as `activity_session_events` with same-user composite FKs, uniqueness, and a role/order field. This supports combining observations and preserving evidence during splits/merges. Manual sessions have explicit `source_kind='manual'` and no fabricated event references; stopwatch-origin sessions retain their TimeSession reference.
3. **State transitions are explicit.** Proposed transitions: `draft -> confirmed | corrected | discarded`; `confirmed -> corrected | discarded`; `corrected -> corrected | discarded`; `discarded` is terminal. Every transition is user-scoped and audited. Discarded means excluded from confirmed totals but retained as evidence; deletion is a separate user-controlled operation.
4. **Duration is bounded.** Confirmed/corrected sessions require aware start/end timestamps, positive interval, and credited duration between zero and elapsed seconds. Paused intervals are excluded from credited duration. Draft/discarded sessions do not contribute allocatable time.
5. **Allocation has one time budget.** For each eligible confirmed/corrected session, sum of time contributions across all goals/targets must be at most the credited duration. The existing PostgreSQL trigger enforces this for writes and duration edits, while `allocate_time` also checks ownership, status and target type. Splitting a session partitions duration; merging sums duration only when intervals do not overlap or the user explicitly resolves overlap. Allocations must be repartitioned/revalidated in the same transaction.
6. **Multiple goal contributions do not multiply time.** Metric and milestone contributions may be recorded for multiple goals independently. Time is a conserved allocation pool: if 60 minutes support two goals, allocate at most 60 total minutes across those goals, not 60 minutes to each.
7. **Manual and stopwatch sources are explicit.** Manual entries are not synthetic device events. Stopwatch sessions remain a distinct source and require pause/resume segments or equivalent accumulated active duration. Preserve offline creation IDs for idempotent sync if offline stopwatch entry is supported.
8. **Corrections are append-only.** Record actor, timestamp, field, before/after values and reason. Apply correction and append audit row atomically. Existing correction trigger prohibits row mutation/deletion; corrected values remain distinct from original observed evidence.
9. **Split conserves.** The sum of child credited durations equals the parent credited duration; preserve event links, source references, and allocation total. Parent/child lineage is immutable and explicit.
10. **Merge preserves provenance.** Merged session retains every source event and stopwatch/manual lineage, plus immutable links to merged source sessions. Do not merge overlapping intervals into extra credited time silently.
11. **History is queryable.** Event, session, correction, contribution, and lineage queries are scoped by authenticated user and support bounded date/source/status filters with stable pagination. Corrections never rewrite original event payloads.
12. **Deletion is explicit.** Retention expiry is never automatic unless a user selects a disclosed policy. Deletion must identify consequences (for example, dependent sessions or correction audit) and must not silently erase evidence required to explain a confirmed record.

## 3. Existing versus required API contracts

Existing route families are under `/api/v1`: `/activity-sources`, `/activity-sources/events`, `/time-sessions`, `/activity-records`, `/targets`, `/tasks`, `/schedule`, `/routines`, `/memory`, and `/diary`.

| Contract | Current state | Proposed contract and dependencies |
| --- | --- | --- |
| Ingest observed event | Exists: `POST /activity-sources/events`; strict type, timestamp, confidence, payload validation; idempotent per source/event ID | Preserve. Add user-scoped history query with date/source/type filters and stable cursor; never expose device credential hash |
| List/revoke source | Exists: authenticated list and owner-scoped revoke | Preserve; add explicit user data export/delete policy before hard-delete route |
| Review observed events | Missing | `GET /activity-events` (or `/activity-sources/events` GET) returning unreviewed and reviewed events; immutable raw event representation and pagination |
| Create activity session | No dedicated route found | `POST /activity-sessions` for manual draft or event-linked draft; server derives user; require provenance discriminator; validate all event/source ownership |
| Confirm session | Missing | `POST /activity-sessions/{id}/confirm`; require valid interval/duration, retain event lineage, atomically transition and make eligible for contributions |
| Correct session | Missing | `POST /activity-sessions/{id}/corrections`; whitelist correctable fields; append immutable audit; recompute/reject allocations atomically |
| Discard observation/session | Missing | `POST /activity-events/{id}/discard` or a review decision on linked draft; retain row and exclusion status. Avoid deleting raw evidence as a synonym for discard |
| Manual time entry | Missing as a first-class route | Create manual ActivitySession with explicit source, timestamps, reason; route through same confirmation and correction rules |
| Stopwatch pause/resume | Missing; current `TimeSession` has running/completed/cancelled | Add pause/resume contracts and persisted active-time segments or equivalent unambiguous accounting; partial unique guard must cover running state |
| Split/merge | Missing | Explicit commands with idempotency key, lineage, conserved duration, preserved evidence and transactional allocation reconciliation |
| Goal time allocation | Service/model exists; no route included in router | `PUT`/`POST` allocation set with target IDs and seconds; atomic total validation; distinguish time allocations from metric/milestone contributions |
| Historical activity query | Existing time-session, activity-record, analytics and source listing are separate | Unified user-scoped query across events/sessions/corrections/contributions, with explicit state/source filters and bounded pagination; do not collapse semantics |
| Personal data export/delete | No account-wide export/delete workflow found | Export first; then explicit per-domain deletion and account deletion plan that handles RESTRICT audit FKs and revokes credentials |

API operations that mutate a session should accept an idempotency key where retry could otherwise duplicate a manual entry, split, merge, contribution, or review action. User ID and ownership must always come from authentication, never request payload.

## 4. PostgreSQL test and migration verification

### Existing safety design

- `tests/test_activity_postgres.py` and `tests/test_activity_migration_postgres.py` skip unless `POSTGRES_TEST_URL` is set.
- Each activity behavior test creates a uniquely named schema and drops only that schema in teardown.
- The migration test creates a uniquely named schema, overrides the Alembic database URL to use that schema, upgrades through the Personal Memory and Activity Engine revisions, checks tables/triggers/cascade behavior, downgrades the Activity Engine revision, verifies prior foreign keys, then drops the isolated schema.
- `.github/workflows/activity-engine-postgres.yml` provisions a dedicated PostgreSQL service database and runs these tests. The general CI workflow also provisions its own service database and applies migrations to that CI-only database.
- Never set `POSTGRES_TEST_URL` to a development or production database. Although tests isolate schemas, the test database must be disposable and dedicated; credentials should not have access to user data.

### Local verification result

Not run against PostgreSQL in this environment. `POSTGRES_TEST_URL` is not configured, and Docker/PostgreSQL CLI tools are unavailable. I did not use the application's configured database because its identity and contents are user data. Safe command in an isolated disposable PostgreSQL service, from `backend/`:

```powershell
$env:POSTGRES_TEST_URL = "postgresql+psycopg://<test-user>:<test-password>@127.0.0.1:<test-port>/<dedicated-disposable-db>"
$env:DATABASE_URL = $env:POSTGRES_TEST_URL
$env:JWT_SECRET_KEY = "test-only-random-secret"
$env:DEBUG = "false"
python -m pytest tests/test_activity_postgres.py tests/test_activity_migration_postgres.py tests/test_activity_contributions.py tests/test_activity_source_api.py -v
```

The dedicated GitHub Actions workflow is the available PostgreSQL verification path when local disposable PostgreSQL is unavailable. Migration upgrade/downgrade safeguards are inspected in code but not newly executed locally.

## 5. Retention and deletion specification

No automatic deletion is introduced by this specification. User-selected retention periods must be explicit, visible, reversible before execution where practical, and scoped by data category.

| Data | Proposed user control | Integrity considerations |
| --- | --- | --- |
| Raw ActivityEvents | Inspect/export; retain indefinitely by default until explicit delete/retention choice; support deletion by date/source | Removing evidence may make confirmed sessions unauditable. Require preview of linked sessions and explicit detach/delete policy |
| ActivitySessions | Inspect/export; user may discard without deletion; explicit delete with dependency preview | Preserve corrections and contribution lineage or require explicit cascading deletion; never silently erase confirmed history |
| ActivityCorrections | Export and inspect; immutable during normal use; removal only as part of explicit parent/account erasure policy | Current DB trigger forbids delete and FK is RESTRICT; account erasure needs a carefully designed privileged erasure path or documented tombstone strategy |
| Contributions | Inspect/export; delete/reverse only through audited correction/reallocation action | Revalidate time capacity and target progress in one transaction |
| Personal memories | Existing archive and permanent delete routes; add export | Deleting/superseding context must not delete diary or activity records |
| Diary entries | Existing per-entry delete; add export and optional user-selected retention | Preserve independence from target/session records |
| Device credentials | Existing revoke prevents future ingestion; raw credential returned once and only HMAC digest stored | Revocation should be immediate; retention of source metadata/events remains separately user-controlled |
| Account | No workflow found; provide export, confirmation, consequences preview, revocation, then delete/anonymize by domain | User FKs generally cascade, but correction RESTRICT references can block deletion. Resolve policy and database behavior before implementing endpoint |

## 6. Migration requirements

No migration is justified merely to document these contracts. A future migration is likely required before observed activity can be confirmed safely:

1. Add an explicit session provenance/source kind and a same-user many-to-many `ActivitySession` ↔ `ActivityEvent` evidence relation with uniqueness and indexes. Define event/session deletion behavior before choosing cascade/restrict.
2. Add explicit lineage for split/merge operations, including parent session references and idempotency metadata if needed.
3. Add stopwatch pause segments or equivalent persisted accounting and source type for manual entries.
4. Consider an immutable lifecycle/review-decision ledger if status changes need full history; current `ActivityCorrection` captures field changes but not every state transition.
5. Do not add retention timestamps or background deletion until the user-facing retention policy is approved and tested.

Any migration must include clean upgrade/downgrade tests in an isolated schema, populated-data upgrade checks, constraint/trigger assertions, and explicit handling of existing rows. No migration was created in this batch.

## 7. Batch 2 dependencies and implementation plan

1. **Approve semantics** for evidence association, state transitions, duration source, overlap handling, deletion dependencies, and whether Target remains the near-term goal target.
2. **Add provenance and evidence schema** with a reversible migration and PostgreSQL upgrade/downgrade tests. Backfill existing sessions as `legacy/unknown`; do not fabricate ActivityEvent references.
3. **Implement event review/session creation** with owner checks, idempotency, raw-event immutability, and explicit manual-vs-observed source.
4. **Implement confirm/correct/discard** transactionally, retaining immutable audit rows and revalidating contributions after corrections.
5. **Implement allocations and multi-goal contribution APIs** over the existing service/trigger, with conservation and concurrency tests.
6. **Implement stopwatch pause/resume/manual entry** only after duration accounting is settled; add offline semantics only if the product requires offline stopwatch use.
7. **Implement split/merge** after evidence relation and lineage exist; property-test duration conservation, event preservation, no overlap inflation, and allocation bounds.
8. **Add history/export/deletion flows** after retention policy and FK erasure behavior are decided.
9. Add frontend review and history UI after backend contracts stabilize.

### Read-only audit result

No source, schema, migration, or configuration files were modified. Existing working-tree changes were preserved. Protected files were not read or changed.
