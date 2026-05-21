from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from backend.core.security import EntraPrincipal, get_current_principal, get_principal_object_id
from backend.modules.admin.models import UserAccount

from backend.modules.admin.service import AdminService
from backend.modules.jobs.service import JobService
from backend.modules.resources.service import ResourceService


@dataclass(frozen=True)
class AuthenticatedUserContext:
    principal: EntraPrincipal
    user: UserAccount


def get_admin_service(request: Request) -> AdminService:
    return request.app.state.admin_service


def get_resource_service(request: Request) -> ResourceService:
    return request.app.state.resource_service


def get_job_service(request: Request) -> JobService:
    return request.app.state.job_service


async def get_authenticated_user_context(
    request: Request,
    principal: EntraPrincipal | None = Depends(get_current_principal),
) -> AuthenticatedUserContext:
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
        )

    principal_id = get_principal_object_id(principal)
    if principal_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal id could not be resolved from the token.",
        )

    admin_service: AdminService = request.app.state.admin_service
    user = await admin_service.ensure_user_exists(
        principal_id,
        email=_get_principal_email(principal),
        display_name=_get_principal_display_name(principal),
    )
    if not user.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not enabled in the application.",
        )

    return AuthenticatedUserContext(principal=principal, user=user)


def _get_principal_email(principal: EntraPrincipal) -> str | None:
    claims = principal.claims
    return claims.get("preferred_username") or claims.get("email") or claims.get("upn")


def _get_principal_display_name(principal: EntraPrincipal) -> str | None:
    claims = principal.claims
    if claims.get("name"):
        return claims["name"]
    first_name = claims.get("given_name")
    last_name = claims.get("family_name")
    if first_name and last_name:
        return f"{first_name} {last_name}"
    return first_name or last_name
