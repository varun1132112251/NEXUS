"""Database models registered with the application metadata."""

from app.models.activity_record import ActivityRecord
from app.models.diary import DiaryEntry
from app.models.habit import Habit
from app.models.project import Project
from app.models.routine_template import RoutineTemplate
from app.models.schedule import ScheduleItem
from app.models.target import Target
from app.models.task import Task
from app.models.time_session import TimeSession
from app.models.user import User

__all__ = ["User", "DiaryEntry", "Target", "Habit", "Project", "Task", "ScheduleItem", "TimeSession", "ActivityRecord", "RoutineTemplate"]
