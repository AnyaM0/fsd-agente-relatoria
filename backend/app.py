from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.http.router import router
from backend.infra.clients import close_app_clients, create_app_clients
from backend.core.config import get_settings
from backend.core.logging import configure_logging
from backend.modules.admin.repository import create_admin_repository
from backend.modules.admin.service import AdminService
from backend.modules.jobs.dispatcher import create_job_dispatcher
from backend.modules.jobs.repository import create_job_repository
from backend.modules.jobs.service import JobService
from backend.modules.notifications import create_notification_service
from backend.modules.resources.repository import create_resource_repository
from backend.modules.resources.service import ResourceService


def _build_cors_allowed_origins(settings) -> list[str]:
    origins = {
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5173",
        "http://localhost:5174",
    }
    origins.update(settings.cors_allowed_origins)
    if settings.frontend_base_url:
        origins.add(settings.frontend_base_url.rstrip("/"))
    return sorted(origins)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(debug=settings.debug)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.clients = create_app_clients(settings)
        app.state.admin_repository = create_admin_repository(settings, app.state.clients)
        app.state.admin_service = AdminService(app.state.admin_repository)
        app.state.resource_repository = create_resource_repository(settings, app.state.clients)
        app.state.resource_service = ResourceService(
            app.state.resource_repository,
            app.state.admin_service,
            app.state.clients,
            settings,
        )
        app.state.notification_service = create_notification_service(settings)
        app.state.job_repository = create_job_repository(settings, app.state.clients)
        app.state.job_dispatcher = create_job_dispatcher(settings, app.state.clients)
        app.state.job_service = JobService(
            app.state.job_repository,
            app.state.job_dispatcher,
            app.state.admin_service,
            app.state.resource_service,
            app.state.clients,
            settings,
        )
        await app.state.admin_service.seed_builtin_agents()
        try:
            yield
        finally:
            await close_app_clients(app.state.clients)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_build_cors_allowed_origins(settings),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix=settings.api_prefix)
    return app
