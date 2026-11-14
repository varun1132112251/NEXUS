from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity_event import ActivityEvent
from app.models.activity_session import ActivitySession
from app.models.activity_session_event import ActivitySessionEvent


def draft_from_application_end(db: Session, event: ActivityEvent) -> ActivitySession | None:
    """Create an evidence-linked review draft from a collector end transition."""
    payload = event.payload or {}
    if event.event_type != "app_focus" or payload.get("transition") != "ended":
        return None
    try:
        started_at = datetime.fromisoformat(str(payload["started_at"]).replace("Z", "+00:00"))
        duration_seconds = int(payload["duration_seconds"])
    except (KeyError, TypeError, ValueError):
        return None
    if started_at.tzinfo is None or started_at.utcoffset() is None or duration_seconds < 0 or event.occurred_at <= started_at:
        return None
    already_drafted = db.scalar(select(ActivitySessionEvent.activity_session_id).where(
        ActivitySessionEvent.activity_event_id == event.id,
        ActivitySessionEvent.user_id == event.user_id,
    ).limit(1))
    if already_drafted:
        return None
    possible_starts = list(db.scalars(select(ActivityEvent).where(
        ActivityEvent.source_id == event.source_id,
        ActivityEvent.user_id == event.user_id,
        ActivityEvent.event_type == "app_focus",
        ActivityEvent.occurred_at >= started_at - timedelta(seconds=1),
        ActivityEvent.occurred_at <= started_at + timedelta(seconds=1),
        ActivityEvent.discarded_at.is_(None),
    ).order_by(ActivityEvent.occurred_at.desc()).limit(10)).all())
    start_event = next((candidate for candidate in possible_starts if
        candidate.payload.get("transition") == "started"
        and candidate.payload.get("process_id") == payload.get("process_id")
        and candidate.payload.get("application") == payload.get("application")
    ), None)
    evidence = [event] + ([start_event] if start_event else [])
    session = ActivitySession(
        user_id=event.user_id,
        title=str(payload.get("application") or "Observed application activity")[:255],
        started_at=started_at,
        ended_at=event.occurred_at,
        duration_seconds=min(duration_seconds, max(0, int((event.occurred_at - started_at).total_seconds()))),
        confidence=event.confidence,
        status="draft",
        source_kind="observed",
    )
    db.add(session)
    db.flush()
    for source_event in evidence:
        db.add(ActivitySessionEvent(activity_session_id=session.id, activity_event_id=source_event.id, user_id=event.user_id))
    return session
