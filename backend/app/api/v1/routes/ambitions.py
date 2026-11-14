from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.ambition import Ambition
from app.models.ambition_goal import AmbitionGoal
from app.models.ambition_milestone import AmbitionMilestone
from app.models.ambition_lifecycle_event import AmbitionLifecycleEvent
from app.models.goal_progress_entry import GoalProgressEntry
from app.models.project import Project
from app.models.user import User
from app.schemas.ambition import (
    AmbitionCreate, AmbitionLifecycle, AmbitionLifecycleRead, AmbitionRead, AmbitionTemplate, AmbitionUpdate,
    GoalCreate, GoalProgressCorrection, GoalProgressCreate, GoalProgressRead, GoalRead,
    GoalUpdate, MilestoneCreate, MilestoneRead, MilestoneUpdate,
)

router = APIRouter(prefix="/ambitions", tags=["ambitions"])

TEMPLATES = [
    ("Health and fitness", "Build a sustainable approach to physical health and movement.", "health"),
    ("Learning and education", "Pursue learning that matters to you over time.", "learning"),
    ("Career and craft", "Develop meaningful work, professional skills, or a craft.", "career"),
    ("Financial security", "Work toward the financial outcomes you choose.", "finance"),
    ("Relationships", "Invest in the relationships and connections you value.", "relationships"),
    ("Creativity", "Make space for creative practice and finished work.", "creative"),
    ("Community and service", "Contribute to causes or communities important to you.", "community"),
    ("Home and environment", "Shape a home and surroundings that support your life.", "home"),
    ("Adventure and exploration", "Plan experiences and places you want to explore.", "adventure"),
    ("Personal resilience", "Develop the capacities that help you meet difficulty.", "wellbeing"),
    ("Family and care", "Support the family and caregiving commitments you choose.", "family"),
    ("Personal contribution", "Build a lasting contribution in a form you define.", "contribution"),
]
MEASUREMENTS = {"count", "duration", "distance", "weight", "currency", "percentage", "proficiency", "custom", "qualitative"}


def owned_ambition(db: Session, item_id: UUID, user_id: UUID, *, lock: bool = False) -> Ambition:
    query = select(Ambition).where(Ambition.id == item_id, Ambition.user_id == user_id)
    if lock:
        query = query.with_for_update()
    item = db.scalar(query)
    if item is None:
        raise HTTPException(status_code=404, detail="Ambition not found.")
    return item


def owned_goal(db: Session, item_id: UUID, user_id: UUID, *, lock: bool = False) -> AmbitionGoal:
    query = select(AmbitionGoal).where(AmbitionGoal.id == item_id, AmbitionGoal.user_id == user_id)
    if lock:
        query = query.with_for_update()
    item = db.scalar(query)
    if item is None:
        raise HTTPException(status_code=404, detail="Ambition goal not found.")
    return item


@router.get("/templates", response_model=list[AmbitionTemplate])
def list_templates():
    return [AmbitionTemplate(title=title, description=description, category=category) for title, description, category in TEMPLATES]


@router.get("", response_model=list[AmbitionRead])
def list_ambitions(include_archived: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(Ambition).where(Ambition.user_id == user.id)
    if not include_archived:
        query = query.where(Ambition.status != "archived")
    return list(db.scalars(query.order_by(Ambition.display_order, Ambition.created_at, Ambition.id)).all())


@router.post("", response_model=AmbitionRead, status_code=status.HTTP_201_CREATED)
def create_ambition(payload: AmbitionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = Ambition(user_id=user.id, **payload.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail="Ambition dates are invalid.") from exc
    db.refresh(item)
    return item


@router.patch("/{ambition_id}", response_model=AmbitionRead)
def update_ambition(ambition_id: UUID, payload: AmbitionUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = owned_ambition(db, ambition_id, user.id, lock=True)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail="Ambition dates are invalid.") from exc
    db.refresh(item)
    return item


@router.post("/{ambition_id}/lifecycle", response_model=AmbitionRead)
def set_ambition_lifecycle(ambition_id: UUID, payload: AmbitionLifecycle, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = owned_ambition(db, ambition_id, user.id, lock=True)
    previous = item.status
    item.status = payload.status
    item.completed_at = date.today() if payload.status == "completed" else None
    if previous != payload.status:
        db.add(AmbitionLifecycleEvent(user_id=user.id, ambition_id=item.id, previous_status=previous, new_status=payload.status, reason=payload.reason))
    db.commit()
    db.refresh(item)
    return item


@router.get("/{ambition_id}/history", response_model=list[AmbitionLifecycleRead])
def ambition_lifecycle_history(ambition_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned_ambition(db, ambition_id, user.id)
    return list(db.scalars(select(AmbitionLifecycleEvent).where(AmbitionLifecycleEvent.ambition_id == ambition_id, AmbitionLifecycleEvent.user_id == user.id).order_by(AmbitionLifecycleEvent.created_at, AmbitionLifecycleEvent.id)).all())


@router.put("/reorder", response_model=list[AmbitionRead])
def reorder_ambitions(ambition_ids: list[UUID] = Query(), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if len(ambition_ids) != len(set(ambition_ids)):
        raise HTTPException(status_code=422, detail="Ambition IDs must be unique.")
    rows = list(db.scalars(select(Ambition).where(Ambition.user_id == user.id, Ambition.id.in_(ambition_ids)).with_for_update()).all()) if ambition_ids else []
    if len(rows) != len(ambition_ids):
        raise HTTPException(status_code=404, detail="One or more ambitions were not found.")
    by_id = {row.id: row for row in rows}
    for order, item_id in enumerate(ambition_ids):
        by_id[item_id].display_order = order
    db.commit()
    return [by_id[item_id] for item_id in ambition_ids]


@router.get("/{ambition_id}/goals", response_model=list[GoalRead])
def list_goals(ambition_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned_ambition(db, ambition_id, user.id)
    return list(db.scalars(select(AmbitionGoal).where(AmbitionGoal.ambition_id == ambition_id, AmbitionGoal.user_id == user.id).order_by(AmbitionGoal.priority, AmbitionGoal.target_date, AmbitionGoal.created_at)).all())


@router.post("/{ambition_id}/goals", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
def create_goal(ambition_id: UUID, payload: GoalCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    parent = owned_ambition(db, ambition_id, user.id)
    if parent.status in {"archived", "completed"}:
        raise HTTPException(status_code=409, detail="Goals cannot be added to a completed or archived ambition.")
    if payload.supporting_project_id and db.scalar(select(Project.id).where(Project.id == payload.supporting_project_id, Project.user_id == user.id)) is None:
        raise HTTPException(status_code=404, detail="Supporting project not found.")
    if payload.measurement_type not in {"qualitative"} and payload.measurement_type in {"duration", "distance", "weight", "currency", "percentage", "custom"} and not payload.measurement_unit:
        raise HTTPException(status_code=422, detail="This measurement type requires a user-defined unit.")
    if payload.measurement_type == "duration" and payload.measurement_unit != "seconds":
        raise HTTPException(status_code=422, detail="Activity time contributions use seconds for duration goals.")
    goal_values = payload.model_dump()
    if goal_values["measurement_type"] == "count" and not goal_values["measurement_unit"]:
        goal_values["measurement_unit"] = "count"
    if goal_values["measurement_type"] == "proficiency" and not goal_values["measurement_unit"]:
        goal_values["measurement_unit"] = "level"
    item = AmbitionGoal(user_id=user.id, ambition_id=ambition_id, **goal_values)
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail="Goal dates or measurement are invalid.") from exc
    db.refresh(item)
    return item


@router.patch("/goals/{goal_id}", response_model=GoalRead)
def update_goal(goal_id: UUID, payload: GoalUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = owned_goal(db, goal_id, user.id, lock=True)
    values = payload.model_dump(exclude_unset=True)
    if values.get("supporting_project_id") and db.scalar(select(Project.id).where(Project.id == values["supporting_project_id"], Project.user_id == user.id)) is None:
        raise HTTPException(status_code=404, detail="Supporting project not found.")
    if "measurement_type" in values or "measurement_unit" in values:
        new_type = values.get("measurement_type", item.measurement_type)
        new_unit = values.get("measurement_unit", item.measurement_unit)
        if new_type != "qualitative" and new_type in {"duration", "distance", "weight", "currency", "percentage", "custom"} and not new_unit:
            raise HTTPException(status_code=422, detail="This measurement type requires a user-defined unit.")
        if new_type == "duration" and new_unit != "seconds":
            raise HTTPException(status_code=422, detail="Activity time contributions use seconds for duration goals.")
        if new_type == "count" and not new_unit:
            new_unit = "count"
            values["measurement_unit"] = new_unit
        if new_type == "proficiency" and not new_unit:
            new_unit = "level"
            values["measurement_unit"] = new_unit
    for key, value in values.items():
        setattr(item, key, value)
    if "status" in values:
        item.completed_at = date.today() if item.status == "completed" else None
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Goal measurement conflicts with existing contributions or dates.") from exc
    db.refresh(item)
    return item


@router.get("/goals/{goal_id}/progress", response_model=list[GoalProgressRead])
def list_goal_progress(goal_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned_goal(db, goal_id, user.id)
    return list(db.scalars(select(GoalProgressEntry).where(GoalProgressEntry.goal_id == goal_id, GoalProgressEntry.user_id == user.id).order_by(GoalProgressEntry.created_at, GoalProgressEntry.id)).all())


@router.post("/goals/{goal_id}/progress", response_model=GoalProgressRead, status_code=status.HTTP_201_CREATED)
def record_goal_progress(goal_id: UUID, payload: GoalProgressCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    goal = owned_goal(db, goal_id, user.id, lock=True)
    if goal.status in {"archived", "completed"}:
        raise HTTPException(status_code=409, detail="Progress cannot be changed on a completed or archived goal.")
    if payload.numeric_delta is not None:
        if goal.measurement_type == "qualitative" or payload.unit != goal.measurement_unit:
            raise HTTPException(status_code=422, detail="Progress unit must match the goal measurement definition.")
        result = goal.current_value + payload.numeric_delta
        if result < 0:
            raise HTTPException(status_code=422, detail="Progress cannot reduce the current value below zero.")
        if payload.numeric_delta < 0 and not payload.reason:
            raise HTTPException(status_code=422, detail="A reason is required for a decrement or correction.")
        goal.current_value = result
        resulting_value = result
    else:
        if goal.measurement_type != "qualitative" or payload.unit is not None:
            raise HTTPException(status_code=422, detail="Qualitative values require a qualitative goal.")
        goal.qualitative_value = payload.qualitative_value
        resulting_value = None
    entry = GoalProgressEntry(user_id=user.id, goal_id=goal.id, numeric_delta=payload.numeric_delta, resulting_value=resulting_value, qualitative_value=payload.qualitative_value, unit=payload.unit, source_kind="manual", reason=payload.reason, details=payload.details)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.post("/goals/{goal_id}/progress/{entry_id}/correct", response_model=GoalProgressRead, status_code=status.HTTP_201_CREATED)
def correct_goal_progress(goal_id: UUID, entry_id: UUID, payload: GoalProgressCorrection, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    goal = owned_goal(db, goal_id, user.id, lock=True)
    original = db.scalar(select(GoalProgressEntry).where(GoalProgressEntry.id == entry_id, GoalProgressEntry.goal_id == goal.id, GoalProgressEntry.user_id == user.id))
    if original is None:
        raise HTTPException(status_code=404, detail="Progress entry not found.")
    if goal.measurement_type == "qualitative":
        if payload.qualitative_value is None or payload.unit is not None:
            raise HTTPException(status_code=422, detail="Provide a qualitative correction without a unit.")
        goal.qualitative_value = payload.qualitative_value
        result = None
    else:
        if payload.numeric_delta is None or payload.unit != goal.measurement_unit:
            raise HTTPException(status_code=422, detail="Numeric correction must use the goal's measurement unit.")
        result = goal.current_value + payload.numeric_delta
        if result < 0:
            raise HTTPException(status_code=422, detail="Correction cannot reduce progress below zero.")
        goal.current_value = result
    entry = GoalProgressEntry(user_id=user.id, goal_id=goal.id, numeric_delta=payload.numeric_delta, resulting_value=result, qualitative_value=payload.qualitative_value, unit=payload.unit, source_kind="correction", corrects_entry_id=original.id, reason=payload.reason, details=payload.details)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/goals/{goal_id}/milestones", response_model=list[MilestoneRead])
def list_milestones(goal_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned_goal(db, goal_id, user.id)
    return list(db.scalars(select(AmbitionMilestone).where(AmbitionMilestone.goal_id == goal_id, AmbitionMilestone.user_id == user.id).order_by(AmbitionMilestone.display_order, AmbitionMilestone.created_at)).all())


@router.post("/goals/{goal_id}/milestones", response_model=MilestoneRead, status_code=status.HTTP_201_CREATED)
def create_milestone(goal_id: UUID, payload: MilestoneCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    goal = owned_goal(db, goal_id, user.id)
    if goal.status in {"completed", "archived"}:
        raise HTTPException(status_code=409, detail="Milestones cannot be added to a completed or archived goal.")
    item = AmbitionMilestone(user_id=user.id, goal_id=goal.id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.patch("/milestones/{milestone_id}", response_model=MilestoneRead)
def update_milestone(milestone_id: UUID, payload: MilestoneUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.scalar(select(AmbitionMilestone).where(AmbitionMilestone.id == milestone_id, AmbitionMilestone.user_id == user.id).with_for_update())
    if item is None:
        raise HTTPException(status_code=404, detail="Milestone not found.")
    values = payload.model_dump(exclude_unset=True)
    previous = item.status
    for key, value in values.items():
        setattr(item, key, value)
    if item.status == "completed" and previous != "completed":
        item.completed_at = date.today()
        goal = owned_goal(db, item.goal_id, user.id, lock=True)
        entry = GoalProgressEntry(user_id=user.id, goal_id=goal.id, numeric_delta=Decimal(1) if goal.measurement_type == "count" else None, resulting_value=goal.current_value + 1 if goal.measurement_type == "count" else None, qualitative_value=None if goal.measurement_type == "count" else f"Completed milestone: {item.title}", unit=goal.measurement_unit if goal.measurement_type == "count" else None, source_kind="milestone", reason=f"Milestone completed: {item.title}")
        if goal.measurement_type == "count":
            goal.current_value += 1
        db.add(entry)
    elif item.status != "completed":
        if previous == "completed":
            goal = owned_goal(db, item.goal_id, user.id, lock=True)
            original = db.scalar(select(GoalProgressEntry).where(GoalProgressEntry.goal_id == goal.id, GoalProgressEntry.user_id == user.id, GoalProgressEntry.source_kind == "milestone", GoalProgressEntry.reason == f"Milestone completed: {item.title}").order_by(GoalProgressEntry.created_at.desc()).limit(1))
            if original is not None and goal.measurement_type == "count":
                goal.current_value = max(Decimal(0), goal.current_value - Decimal(1))
                db.add(GoalProgressEntry(user_id=user.id, goal_id=goal.id, numeric_delta=Decimal(-1), resulting_value=goal.current_value, unit=goal.measurement_unit, source_kind="correction", corrects_entry_id=original.id, reason=f"Milestone reopened: {item.title}"))
            elif original is not None:
                db.add(GoalProgressEntry(user_id=user.id, goal_id=goal.id, qualitative_value=f"Reopened milestone: {item.title}", source_kind="correction", corrects_entry_id=original.id, reason=f"Milestone reopened: {item.title}"))
        item.completed_at = None
    db.commit(); db.refresh(item)
    return item


