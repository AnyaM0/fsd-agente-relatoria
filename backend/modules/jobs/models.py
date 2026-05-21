from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


JobStatus = Literal[
    "queued",
    "validating",
    "downloading_resources",
    "preparing_audio",
    "transcribing",
    "waiting_transcription_batch",
    "segmenting",
    "running_agent",
    "uploading_artifacts",
    "completed",
    "failed",
    "dead_lettered",
    "canceled",
]


class JobDeployRequest(BaseModel):
    agent_id: str
    resource_ids: list[str]
    options: dict[str, Any] = Field(default_factory=dict)


class JobStepRecord(BaseModel):
    name: str
    status: Literal["pending", "running", "completed", "failed"]
    message: str = ""
    started_at: str | None = None
    finished_at: str | None = None


class JobRecord(BaseModel):
    job_id: str
    owner_object_id: str
    agent_id: str
    job_tag: str
    resource_ids: list[str]
    status: JobStatus
    current_step: str
    progress: int = 0
    dispatch_backend: Literal["service_bus", "noop"]
    worker_payload: dict[str, Any]
    worker_state: dict[str, Any] = Field(default_factory=dict)
    attempt_count: int = 0
    max_attempts: int = 3
    next_retry_at: str | None = None
    last_attempt_started_at: str | None = None
    last_heartbeat_at: str | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)
    pipeline_steps: list[JobStepRecord] = Field(default_factory=list)
    transcript_summary: dict[str, Any] | None = None
    final_result_summary: dict[str, Any] | None = None
    log_summary: dict[str, Any] | None = None
    transcript_text: str | None = None
    final_result_text: str | None = None
    logs_text: str | None = None
    notification_status: Literal["pending", "sent", "skipped", "failed"] | None = None
    notification_recipient: str | None = None
    notification_error: str | None = None
    notification_sent_at: str | None = None
    azure_transcription_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    error: dict[str, Any] | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class JobArtifactRecord(BaseModel):
    artifact_key: str
    filename: str
    content_type: str
    size_bytes: int | None = None
    available: bool = True
    download_path: str | None = None


class JobActionResult(BaseModel):
    job_id: str
    status: JobStatus
    current_step: str
    progress: int
    message: str
