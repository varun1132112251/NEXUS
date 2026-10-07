from fastapi import APIRouter

from app.api.v1.routes.activity_records import router as activity_records_router
from app.api.v1.routes.analytics import router as analytics_router
from app.api.v1.routes.diary import router as diary_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.habits import router as habits_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.projects import router as projects_router
from app.api.v1.routes.profile import router as profile_router
from app.api.v1.routes.schedules import router as schedules_router
from app.api.v1.routes.routines import router as routines_router
from app.api.v1.routes.targets import router as targets_router
from app.api.v1.routes.tasks import router as tasks_router
from app.api.v1.routes.time_sessions import router as time_sessions_router
from app.api.v1.routes.users import router as users_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(activity_records_router)
api_router.include_router(analytics_router)
api_router.include_router(diary_router)
api_router.include_router(users_router)
api_router.include_router(profile_router)
api_router.include_router(targets_router)
api_router.include_router(habits_router)
api_router.include_router(projects_router)
api_router.include_router(tasks_router)
api_router.include_router(schedules_router)
api_router.include_router(routines_router)
api_router.include_router(time_sessions_router)
