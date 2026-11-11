"""Ownership-preserving unlink operations used before parent deletion."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.activity_goal_contribution import ActivityGoalContribution
from app.models.activity_session import ActivitySession
from app.models.habit import Habit
from app.models.project import Project
from app.models.schedule import ScheduleItem
from app.models.target import Target
from app.models.task import Task
from app.models.time_session import TimeSession


class ReferencedTargetError(ValueError):
    """A target with accounting history must be retained or explicitly archived."""


def unlink_owned_references(db: Session, model: type, item_id: UUID, user_id: UUID) -> None:
    references = {
        Task: ((ScheduleItem, "task_id"), (TimeSession, "task_id"), (ActivitySession, "task_id")),
        Project: (
            (Task, "project_id"), (ScheduleItem, "project_id"),
            (TimeSession, "project_id"), (ActivitySession, "project_id"),
        ),
        Habit: ((ScheduleItem, "habit_id"), (TimeSession, "habit_id"), (ActivitySession, "habit_id")),
        ScheduleItem: ((TimeSession, "schedule_item_id"), (ActivitySession, "schedule_item_id")),
        Target: ((Task, "target_id"), (ScheduleItem, "target_id"), (TimeSession, "target_id")),
    }
    if model is Target and db.scalar(
        select(ActivityGoalContribution.id).where(ActivityGoalContribution.target_id == item_id).limit(1)
    ) is not None:
        raise ReferencedTargetError("Target has contribution history and cannot be deleted")

    for child_model, column_name in references.get(model, ()):
        column = getattr(child_model, column_name)
        db.execute(
            update(child_model)
            .where(child_model.user_id == user_id, column == item_id)
            .values({column_name: None})
            .execution_options(synchronize_session=False)
        )
