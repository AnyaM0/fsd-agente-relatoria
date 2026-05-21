from __future__ import annotations

from fastapi import APIRouter

from backend.http.routes.admin import router as admin_router
from backend.http.routes.auth import router as auth_router
from backend.http.routes.jobs import router as jobs_router
from backend.http.routes.resources import router as resources_router
from backend.http.routes.system import router as system_router

router = APIRouter()
router.include_router(system_router)
router.include_router(auth_router)
router.include_router(admin_router)
router.include_router(resources_router)
router.include_router(jobs_router)
