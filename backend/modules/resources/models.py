from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


ResourceKind = Literal["audio", "video", "ppt"]
StorageBackend = Literal["blob", "local"]
UploadStatus = Literal["pending", "ready"]


class ResourceRecord(BaseModel):
    resource_id: str
    owner_object_id: str
    agent_id: str
    filename: str
    content_type: str
    size_bytes: int
    resource_kind: ResourceKind
    storage_backend: StorageBackend
    storage_path: str
    upload_status: UploadStatus = "ready"
    created_at: str = Field(default_factory=utc_now_iso)


class UploadUrlRequest(BaseModel):
    agent_id: str
    filename: str
    content_type: str
    size_bytes: int


class UploadUrlResponse(BaseModel):
    resource_id: str
    upload_url: str
    blob_path: str
    upload_expires_at: str


class ResourceUsageSummary(BaseModel):
    job_id: str
    status: str
    current_step: str
    created_at: str
    completed_at: str | None = None


class ResourceView(ResourceRecord):
    usage_count: int = 0
    latest_job: ResourceUsageSummary | None = None
    related_jobs: list[ResourceUsageSummary] = Field(default_factory=list)


class ResourcePreviewLink(BaseModel):
    preview_url: str | None = None
    preview_mode: Literal["office_online", "direct", "none"] = "none"
