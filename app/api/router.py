from fastapi import APIRouter

from app.api.admin import router as admin_router
from app.api.demo import router as demo_router
from app.api.health import router as health_router
from app.api.services import router as services_router

api_router = APIRouter()
api_router.include_router(admin_router)
api_router.include_router(health_router)
api_router.include_router(demo_router)
api_router.include_router(services_router)
