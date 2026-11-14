"""Database models registered with the application metadata."""

from app.models.activity_record import ActivityRecord
from app.models.activity_correction import ActivityCorrection
from app.models.activity_event import ActivityEvent
from app.models.activity_goal_contribution import ActivityGoalContribution
from app.models.activity_session import ActivitySession
from app.models.activity_session_event import ActivitySessionEvent
from app.models.activity_session_lineage import ActivitySessionLineage
from app.models.activity_source import ActivitySource
from app.models.ambition import Ambition
from app.models.ambition_goal import AmbitionGoal
from app.models.ambition_milestone import AmbitionMilestone
from app.models.ambition_lifecycle_event import AmbitionLifecycleEvent
from app.models.goal_progress_entry import GoalProgressEntry
from app.models.auth_identity import AuthIdentity
from app.models.auth_token import AuthToken
from app.models.diary import DiaryEntry
from app.models.habit import Habit
from app.models.project import Project
from app.models.personal_memory import PersonalMemory
from app.models.routine_template import RoutineTemplate
from app.models.schedule import ScheduleItem
from app.models.schedule_status_event import ScheduleStatusEvent
from app.models.target import Target
from app.models.task import Task
from app.models.task_status_event import TaskStatusEvent
from app.models.time_session import TimeSession
from app.models.time_session_segment import TimeSessionSegment
from app.models.user import User
from app.models.user_profile import UserProfile

__all__ = [
    "User",
    "UserProfile",
    "AuthIdentity",
    "AuthToken",
    "DiaryEntry",
    "Target",
    "Habit",
    "Project",
    "Task",
    "TaskStatusEvent",
    "ScheduleItem",
    "ScheduleStatusEvent",
    "TimeSession",
    "TimeSessionSegment",
    "ActivityRecord",
    "ActivitySource",
    "ActivityEvent",
    "ActivitySession",
    "ActivitySessionEvent",
    "ActivitySessionLineage",
    "ActivityGoalContribution",
    "ActivityCorrection",
    "RoutineTemplate",
    "PersonalMemory",
    "Ambition",
    "AmbitionGoal",
    "AmbitionMilestone",
    "AmbitionLifecycleEvent",
    "GoalProgressEntry",
]
