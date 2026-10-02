from fastapi import APIRouter

from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.habits import router as habits_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.projects import router as projects_router
from app.api.v1.routes.targets import router as targets_router
from app.api.v1.routes.tasks import router as tasks_router
from app.api.v1.routes.users import router as users_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(targets_router)
api_router.include_router(habits_router)
api_router.include_router(projects_router)
api_router.include_router(tasks_router)
