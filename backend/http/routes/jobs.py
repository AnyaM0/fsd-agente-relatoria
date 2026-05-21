from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from backend.http.dependencies import (
    AuthenticatedUserContext,
    get_authenticated_user_context,
    get_job_service,
)
from backend.modules.jobs.models import JobActionResult, JobArtifactRecord, JobDeployRequest, JobRecord
from backend.modules.jobs.service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/deploy", response_model=JobRecord, status_code=status.HTTP_201_CREATED)
async def deploy_job(
    payload: JobDeployRequest,
    user_context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    job_service: JobService = Depends(get_job_service),
) -> JobRecord:
    try:
        return await job_service.deploy_job(user=user_context.user, payload=payload)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[JobRecord])
async def list_jobs(
    user_context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    job_service: JobService = Depends(get_job_service),
) -> list[JobRecord]:
    return await job_service.list_jobs(owner_object_id=user_context.user.entra_object_id)


@router.get("/{job_id}", response_model=JobRecord)
async def get_job(
    job_id: str,
    user_context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    job_service: JobService = Depends(get_job_service),
) -> JobRecord:
    record = await job_service.get_job(
        owner_object_id=user_context.user.entra_object_id,
        job_id=job_id,
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return record


@router.get("/{job_id}/artifacts", response_model=list[JobArtifactRecord])
async def list_job_artifacts(
    job_id: str,
    user_context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    job_service: JobService = Depends(get_job_service),
) -> list[JobArtifactRecord]:
    try:
        return await job_service.list_artifacts(
            owner_object_id=user_context.user.entra_object_id,
            job_id=job_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{job_id}/artifacts/{artifact_key}")
async def download_job_artifact(
    job_id: str,
    artifact_key: str,
    user_context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    job_service: JobService = Depends(get_job_service),
) -> Response:
    try:
        content, artifact = await job_service.get_artifact_content(
            owner_object_id=user_context.user.entra_object_id,
            job_id=job_id,
            artifact_key=artifact_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    headers = {"Content-Disposition": f'attachment; filename="{artifact.filename}"'}
    return Response(content=content, media_type=artifact.content_type, headers=headers)


@router.post("/{job_id}/cancel", response_model=JobActionResult)
async def cancel_job(
    job_id: str,
    user_context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    job_service: JobService = Depends(get_job_service),
) -> JobActionResult:
    try:
        return await job_service.cancel_job(
            owner_object_id=user_context.user.entra_object_id,
            job_id=job_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{job_id}/retry", response_model=JobActionResult)
async def retry_job(
    job_id: str,
    user_context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    job_service: JobService = Depends(get_job_service),
) -> JobActionResult:
    try:
        return await job_service.retry_job(
            owner_object_id=user_context.user.entra_object_id,
            job_id=job_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{job_id}/requeue", response_model=JobActionResult)
async def requeue_job(
    job_id: str,
    user_context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    job_service: JobService = Depends(get_job_service),
) -> JobActionResult:
    try:
        return await job_service.requeue_job(
            owner_object_id=user_context.user.entra_object_id,
            job_id=job_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
