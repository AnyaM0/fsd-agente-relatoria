from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.core.security import EntraPrincipal, require_admin_principal
from backend.http.dependencies import get_admin_service
from backend.http.dependencies import get_job_service
from backend.modules.admin.models import (
    AdminCapabilities,
    AgentCreateRequest,
    AgentDefinition,
    AgentUpdateRequest,
    UserAccount,
    UserAgentAccessUpdateRequest,
    UserUpsertRequest,
)
from backend.modules.admin.service import AdminService
from backend.modules.jobs.models import JobActionResult, JobRecord
from backend.modules.jobs.service import JobService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/capabilities", response_model=AdminCapabilities)
async def get_admin_capabilities(
    admin_service: AdminService = Depends(get_admin_service),
    principal: EntraPrincipal = Depends(require_admin_principal),
) -> AdminCapabilities:
    _ = principal
    return await admin_service.get_capabilities()


@router.get("/agents", response_model=list[AgentDefinition])
async def list_agents(
    admin_service: AdminService = Depends(get_admin_service),
    principal: EntraPrincipal = Depends(require_admin_principal),
) -> list[AgentDefinition]:
    _ = principal
    return await admin_service.list_agents()


@router.post("/agents", response_model=AgentDefinition, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreateRequest,
    admin_service: AdminService = Depends(get_admin_service),
    principal: EntraPrincipal = Depends(require_admin_principal),
) -> AgentDefinition:
    _ = principal
    existing = await admin_service.get_agent(payload.agent_id)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent already exists.")
    return await admin_service.create_agent(payload)


@router.put("/agents/{agent_id}", response_model=AgentDefinition)
async def update_agent(
    agent_id: str,
    payload: AgentUpdateRequest,
    admin_service: AdminService = Depends(get_admin_service),
    principal: EntraPrincipal = Depends(require_admin_principal),
) -> AgentDefinition:
    _ = principal
    updated = await admin_service.update_agent(agent_id, payload)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return updated


@router.get("/users", response_model=list[UserAccount])
async def list_users(
    admin_service: AdminService = Depends(get_admin_service),
    principal: EntraPrincipal = Depends(require_admin_principal),
) -> list[UserAccount]:
    _ = principal
    return await admin_service.list_users()


@router.get("/users/{entra_object_id}", response_model=UserAccount)
async def get_user(
    entra_object_id: str,
    admin_service: AdminService = Depends(get_admin_service),
    principal: EntraPrincipal = Depends(require_admin_principal),
) -> UserAccount:
    _ = principal
    user = await admin_service.get_user(entra_object_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


@router.put("/users/{entra_object_id}", response_model=UserAccount)
async def upsert_user(
    entra_object_id: str,
    payload: UserUpsertRequest,
    admin_service: AdminService = Depends(get_admin_service),
    principal: EntraPrincipal = Depends(require_admin_principal),
) -> UserAccount:
    _ = principal
    try:
        return await admin_service.upsert_user(entra_object_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/users/{entra_object_id}/agents", response_model=UserAccount)
async def set_user_agent_access(
    entra_object_id: str,
    payload: UserAgentAccessUpdateRequest,
    admin_service: AdminService = Depends(get_admin_service),
    principal: EntraPrincipal = Depends(require_admin_principal),
) -> UserAccount:
    _ = principal
    try:
        updated = await admin_service.set_user_allowed_agents(entra_object_id, payload.allowed_agent_ids)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return updated


@router.post("/users/{entra_object_id}/agents/{agent_id}", response_model=UserAccount)
async def grant_agent_access(
    entra_object_id: str,
    agent_id: str,
    admin_service: AdminService = Depends(get_admin_service),
    principal: EntraPrincipal = Depends(require_admin_principal),
) -> UserAccount:
    _ = principal
    try:
        updated = await admin_service.grant_agent_access(entra_object_id, agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return updated


@router.delete("/users/{entra_object_id}/agents/{agent_id}", response_model=UserAccount)
async def revoke_agent_access(
    entra_object_id: str,
    agent_id: str,
    admin_service: AdminService = Depends(get_admin_service),
    principal: EntraPrincipal = Depends(require_admin_principal),
) -> UserAccount:
    _ = principal
    updated = await admin_service.revoke_agent_access(entra_object_id, agent_id)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return updated


@router.get("/users/{entra_object_id}/jobs", response_model=list[JobRecord])
async def list_user_jobs(
    entra_object_id: str,
    admin_service: AdminService = Depends(get_admin_service),
    job_service: JobService = Depends(get_job_service),
    principal: EntraPrincipal = Depends(require_admin_principal),
) -> list[JobRecord]:
    _ = principal
    user = await admin_service.get_user(entra_object_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return await job_service.list_jobs_for_admin(owner_object_id=entra_object_id)


@router.post("/users/{entra_object_id}/jobs/{job_id}/rescue", response_model=JobActionResult)
async def rescue_user_job(
    entra_object_id: str,
    job_id: str,
    admin_service: AdminService = Depends(get_admin_service),
    job_service: JobService = Depends(get_job_service),
    principal: EntraPrincipal = Depends(require_admin_principal),
) -> JobActionResult:
    _ = principal
    user = await admin_service.get_user(entra_object_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    try:
        return await job_service.rescue_stale_job(
            owner_object_id=entra_object_id,
            job_id=job_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/users/{entra_object_id}/jobs/{job_id}/retry", response_model=JobActionResult)
async def retry_user_job(
    entra_object_id: str,
    job_id: str,
    admin_service: AdminService = Depends(get_admin_service),
    job_service: JobService = Depends(get_job_service),
    principal: EntraPrincipal = Depends(require_admin_principal),
) -> JobActionResult:
    _ = principal
    user = await admin_service.get_user(entra_object_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    try:
        return await job_service.retry_job(
            owner_object_id=entra_object_id,
            job_id=job_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
