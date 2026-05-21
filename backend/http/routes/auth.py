from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.core.security import EntraPrincipal, get_current_principal, get_principal_object_id
from backend.http.dependencies import _get_principal_display_name, _get_principal_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def auth_me(
    request: Request,
    principal: EntraPrincipal | None = Depends(get_current_principal),
) -> dict[str, object]:
    user = None
    allowed_agents: list[dict[str, object]] = []

    if principal is not None:
        principal_id = get_principal_object_id(principal)
        if principal_id is not None:
            admin_service = request.app.state.admin_service
            user = await admin_service.ensure_user_exists(
                principal_id,
                email=_get_principal_email(principal),
                display_name=_get_principal_display_name(principal),
            )
            if user is not None:
                for agent_id in user.allowed_agent_ids:
                    agent = await admin_service.get_agent(agent_id)
                    if agent is not None and agent.enabled:
                        allowed_agents.append(
                            {
                                "agent_id": agent.agent_id,
                                "display_name": agent.display_name,
                                "accepted_resource_kinds": agent.accepted_resource_kinds,
                                "supports_audio": agent.supports_audio,
                                "supports_ppt": agent.supports_ppt,
                            }
                        )

    return {
        "authenticated": principal is not None,
        "principal": None if principal is None else principal.as_dict(),
        "user": None if user is None else user.model_dump(),
        "allowed_agents": allowed_agents,
    }
