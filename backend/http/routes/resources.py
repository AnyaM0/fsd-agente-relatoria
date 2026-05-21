from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status

from backend.http.dependencies import (
    AuthenticatedUserContext,
    get_authenticated_user_context,
    get_job_service,
    get_resource_service,
)
from backend.modules.jobs.models import JobRecord
from backend.modules.jobs.service import JobService
from backend.modules.resources.models import (
    ResourcePreviewLink,
    ResourceRecord,
    ResourceUsageSummary,
    ResourceView,
    UploadUrlRequest,
    UploadUrlResponse,
)
from backend.modules.resources.service import ResourceService

router = APIRouter(prefix="/resources", tags=["resources"])


@router.post("/upload-url", response_model=UploadUrlResponse, status_code=status.HTTP_201_CREATED)
async def request_upload_url(
    body: UploadUrlRequest,
    user_context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    resource_service: ResourceService = Depends(get_resource_service),
) -> UploadUrlResponse:
    try:
        return await resource_service.create_upload_url(
            user=user_context.user,
            agent_id=body.agent_id,
            filename=body.filename,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc


@router.post("/{resource_id}/confirm", response_model=ResourceRecord)
async def confirm_upload(
    resource_id: str,
    user_context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    resource_service: ResourceService = Depends(get_resource_service),
) -> ResourceRecord:
    try:
        return await resource_service.confirm_upload(
            owner_object_id=user_context.user.entra_object_id,
            resource_id=resource_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/upload", response_model=ResourceRecord, status_code=status.HTTP_201_CREATED)
async def upload_resource(
    agent_id: str = Form(...),
    file: UploadFile = File(...),
    user_context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    resource_service: ResourceService = Depends(get_resource_service),
) -> ResourceRecord:
    try:
        return await resource_service.upload_resource(
            user=user_context.user,
            agent_id=agent_id,
            upload=file,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _build_resource_view(record: ResourceRecord, jobs: list[JobRecord]) -> ResourceView:
    related_jobs = [job for job in jobs if record.resource_id in job.resource_ids]
    related_job_summaries: list[ResourceUsageSummary] = []
    latest_job = None
    if related_jobs:
        sorted_jobs = sorted(related_jobs, key=lambda item: item.created_at, reverse=True)
        related_job_summaries = [
            ResourceUsageSummary(
                job_id=job.job_id,
                status=job.status,
                current_step=job.current_step,
                created_at=job.created_at,
                completed_at=job.completed_at,
            )
            for job in sorted_jobs
        ]
        latest = sorted_jobs[0]
        latest_job = related_job_summaries[0]
    return ResourceView(
        **record.model_dump(),
        usage_count=len(related_jobs),
        latest_job=latest_job,
        related_jobs=related_job_summaries,
    )


@router.get("", response_model=list[ResourceView])
async def list_resources(
    agent_id: str | None = None,
    user_context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    resource_service: ResourceService = Depends(get_resource_service),
    job_service: JobService = Depends(get_job_service),
) -> list[ResourceView]:
    records = await resource_service.list_resources(
        owner_object_id=user_context.user.entra_object_id,
        agent_id=agent_id,
    )
    jobs = await job_service.list_jobs(owner_object_id=user_context.user.entra_object_id)
    return [_build_resource_view(record, jobs) for record in records]


@router.get("/{resource_id}", response_model=ResourceView)
async def get_resource(
    resource_id: str,
    user_context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    resource_service: ResourceService = Depends(get_resource_service),
    job_service: JobService = Depends(get_job_service),
) -> ResourceView:
    record = await resource_service.get_resource(
        owner_object_id=user_context.user.entra_object_id,
        resource_id=resource_id,
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")
    jobs = await job_service.list_jobs(owner_object_id=user_context.user.entra_object_id)
    return _build_resource_view(record, jobs)


@router.get("/{resource_id}/content")
async def get_resource_content(
    resource_id: str,
    user_context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    resource_service: ResourceService = Depends(get_resource_service),
) -> Response:
    record = await resource_service.get_resource(
        owner_object_id=user_context.user.entra_object_id,
        resource_id=resource_id,
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")

    content = await resource_service.read_resource_content(record=record)
    headers = {"Content-Disposition": f'inline; filename="{record.filename}"'}
    return Response(content=content, media_type=record.content_type, headers=headers)


@router.get("/{resource_id}/preview-url", response_model=ResourcePreviewLink)
async def get_resource_preview_url(
    resource_id: str,
    user_context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    resource_service: ResourceService = Depends(get_resource_service),
) -> ResourcePreviewLink:
    record = await resource_service.get_resource(
        owner_object_id=user_context.user.entra_object_id,
        resource_id=resource_id,
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")

    if record.resource_kind != "ppt":
        return ResourcePreviewLink(preview_mode="none")

    preview_url = await resource_service.get_resource_preview_url(record=record)
    if not preview_url:
        return ResourcePreviewLink(preview_mode="none")

    office_viewer = (
        "https://view.officeapps.live.com/op/embed.aspx?src="
        f"{quote(preview_url, safe='')}"
    )
    return ResourcePreviewLink(preview_url=office_viewer, preview_mode="office_online")
