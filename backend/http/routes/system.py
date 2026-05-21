from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "cosmos_enabled": settings.cosmos_enabled,
        "blob_enabled": settings.blob_enabled,
        "entra_enabled": settings.entra_enabled,
        "entra_configured": settings.entra_configured,
        "authenticated": False,
    }

