from __future__ import annotations

import mimetypes
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from backend.core.config import Settings
from backend.infra.clients import AppClients
from backend.modules.admin.models import UserAccount
from backend.modules.admin.service import AdminService
from backend.modules.jobs.dispatcher import JobDispatcher
from backend.modules.jobs.models import JobActionResult, JobArtifactRecord, JobDeployRequest, JobRecord
from backend.modules.jobs.repository import JobRepository
from backend.modules.resources.models import ResourceRecord
from backend.modules.resources.service import ResourceService


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobService:
    def __init__(
        self,
        repository: JobRepository,
        dispatcher: JobDispatcher,
        admin_service: AdminService,
        resource_service: ResourceService,
        clients: AppClients,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.dispatcher = dispatcher
        self.admin_service = admin_service
        self.resource_service = resource_service
        self.clients = clients
        self.settings = settings

    async def deploy_job(self, *, user: UserAccount, payload: JobDeployRequest) -> JobRecord:
        agent = await self.admin_service.get_agent(payload.agent_id)
        if agent is None or not agent.enabled:
            raise ValueError("Agent is not available.")
        if payload.agent_id not in user.allowed_agent_ids:
            raise PermissionError("Agent is not enabled for this user.")
        if not payload.resource_ids:
            raise ValueError("At least one resource must be selected.")

        resources = await self._load_and_validate_resources(user, agent.agent_id, payload.resource_ids)
        self._validate_resource_mix(agent, resources)

        job_id = uuid.uuid4().hex
        worker_payload = {
            "job_id": job_id,
            "owner_object_id": user.entra_object_id,
            "owner_email": user.email,
            "owner_display_name": user.display_name,
            "agent_id": agent.agent_id,
            "job_tag": agent.job_tag,
            "pipeline_domain": agent.pipeline_domain,
            "resource_ids": [item.resource_id for item in resources],
            "resources": [item.model_dump() for item in resources],
            "options": payload.options,
        }
        dispatch_result = await self.dispatcher.dispatch(worker_payload)
        now = utc_now_iso()
        job = JobRecord(
            job_id=job_id,
            owner_object_id=user.entra_object_id,
            agent_id=agent.agent_id,
            job_tag=agent.job_tag,
            resource_ids=[item.resource_id for item in resources],
            status="queued",
            current_step="queued",
            progress=0,
            dispatch_backend=dispatch_result.backend,  # type: ignore[arg-type]
            worker_payload=worker_payload,
            attempt_count=0,
            max_attempts=self.settings.jobs_max_attempts,
            artifacts={},
            created_at=now,
            updated_at=now,
        )
        return await self.repository.create(job)

    async def list_jobs(self, *, owner_object_id: str) -> list[JobRecord]:
        return await self.repository.list_for_owner(owner_object_id)

    async def list_jobs_for_admin(self, *, owner_object_id: str) -> list[JobRecord]:
        return await self.repository.list_for_owner(owner_object_id)

    async def get_job(self, *, owner_object_id: str, job_id: str) -> JobRecord | None:
        return await self.repository.get(owner_object_id, job_id)

    async def get_job_for_admin(self, *, owner_object_id: str, job_id: str) -> JobRecord | None:
        return await self.repository.get(owner_object_id, job_id)

    async def list_artifacts(self, *, owner_object_id: str, job_id: str) -> list[JobArtifactRecord]:
        job = await self.get_job(owner_object_id=owner_object_id, job_id=job_id)
        if job is None:
            raise ValueError("Job not found.")
        return self._build_artifact_records(job)

    async def get_artifact_content(
        self,
        *,
        owner_object_id: str,
        job_id: str,
        artifact_key: str,
    ) -> tuple[bytes, JobArtifactRecord]:
        job = await self.get_job(owner_object_id=owner_object_id, job_id=job_id)
        if job is None:
            raise ValueError("Job not found.")
        records = {item.artifact_key: item for item in self._build_artifact_records(job)}
        artifact = records.get(artifact_key)
        if artifact is None or artifact.download_path is None:
            raise ValueError("Artifact not found.")

        if job.artifacts.get("storage_backend") == "blob":
            blob_client = self.clients.blob_service_client.get_blob_client(
                container=self.settings.blob_artifacts_container_name,
                blob=artifact.download_path,
            )
            stream = await blob_client.download_blob()
            return await stream.readall(), artifact

        local_path = Path(artifact.download_path).expanduser().resolve()
        if not local_path.exists():
            raise ValueError("Artifact file is not available.")
        return local_path.read_bytes(), artifact

    async def cancel_job(self, *, owner_object_id: str, job_id: str) -> JobActionResult:
        job = await self.get_job(owner_object_id=owner_object_id, job_id=job_id)
        if job is None:
            raise ValueError("Job not found.")
        if job.status == "completed":
            raise ValueError("Completed jobs cannot be canceled.")
        updated = job.model_copy(
            update={
                "status": "canceled",
                "current_step": "canceled",
                "updated_at": utc_now_iso(),
                "next_retry_at": None,
            }
        )
        await self.repository.update(updated)
        return JobActionResult(
            job_id=updated.job_id,
            status=updated.status,
            current_step=updated.current_step,
            progress=updated.progress,
            message="Job canceled.",
        )

    async def retry_job(self, *, owner_object_id: str, job_id: str) -> JobActionResult:
        job = await self.get_job(owner_object_id=owner_object_id, job_id=job_id)
        if job is None:
            raise ValueError("Job not found.")
        if job.status not in {"failed", "dead_lettered", "canceled"}:
            raise ValueError("Only failed, dead-lettered, or canceled jobs can be retried.")
        await self._dispatch_existing_job(job, reset_state=True)
        return JobActionResult(
            job_id=job.job_id,
            status="queued",
            current_step="queued",
            progress=0,
            message="Job re-dispatched.",
        )

    async def requeue_job(self, *, owner_object_id: str, job_id: str) -> JobActionResult:
        job = await self.get_job(owner_object_id=owner_object_id, job_id=job_id)
        if job is None:
            raise ValueError("Job not found.")
        await self._dispatch_existing_job(job, reset_state=False)
        return JobActionResult(
            job_id=job.job_id,
            status="queued",
            current_step="queued",
            progress=job.progress,
            message="Job requeued.",
        )

    async def rescue_stale_job(self, *, owner_object_id: str, job_id: str) -> JobActionResult:
        job = await self.get_job(owner_object_id=owner_object_id, job_id=job_id)
        if job is None:
            raise ValueError("Job not found.")
        if job.status in {"completed", "failed", "dead_lettered", "canceled", "queued"}:
            raise ValueError("Only in-flight jobs can be rescued.")
        if not self._is_job_stale(job):
            raise ValueError("Job is not stale yet.")

        await self._dispatch_existing_job(job, reset_state=True)
        return JobActionResult(
            job_id=job.job_id,
            status="queued",
            current_step="queued",
            progress=0,
            message="Stale job rescued and re-dispatched.",
        )

    async def mark_job_failed_or_retry(
        self,
        *,
        record: JobRecord,
        error_type: str,
        error_message: str,
    ) -> JobRecord:
        attempt_count = record.attempt_count + 1
        now = utc_now_iso()
        if attempt_count < record.max_attempts and self.settings.servicebus_enabled:
            next_retry_at = datetime.now(timezone.utc).replace(microsecond=0)
            updated = record.model_copy(
                update={
                    "status": "queued",
                    "current_step": "queued",
                    "attempt_count": attempt_count,
                    "error": {"type": error_type, "message": error_message},
                    "updated_at": now,
                    "next_retry_at": next_retry_at.isoformat(),
                }
            )
            updated = await self.repository.update(updated)
            await self.dispatcher.dispatch(
                updated.worker_payload,
                delay_seconds=self.settings.servicebus_job_retry_delay_seconds,
            )
            return updated

        updated = record.model_copy(
            update={
                "status": "dead_lettered",
                "current_step": "dead_lettered",
                "attempt_count": attempt_count,
                "error": {"type": error_type, "message": error_message},
                "updated_at": now,
                "completed_at": now,
                "next_retry_at": None,
            }
        )
        return await self.repository.update(updated)

    async def _load_and_validate_resources(
        self,
        user: UserAccount,
        agent_id: str,
        resource_ids: list[str],
    ) -> list[ResourceRecord]:
        resources: list[ResourceRecord] = []
        for resource_id in resource_ids:
            record = await self.resource_service.get_resource(
                owner_object_id=user.entra_object_id,
                resource_id=resource_id,
            )
            if record is None:
                raise ValueError(f"Resource not found or inaccessible: {resource_id}.")
            if record.agent_id != agent_id:
                raise ValueError("All selected resources must belong to the same agent.")
            resources.append(record)
        return resources

    def _validate_resource_mix(self, agent, resources: list[ResourceRecord]) -> None:
        kinds = {item.resource_kind for item in resources}
        if any(kind not in agent.accepted_resource_kinds for kind in kinds):
            raise ValueError("One or more resources are not supported by this agent.")
        has_primary_media = any(kind in {"audio", "video"} for kind in kinds)
        if agent.requires_primary_media and not has_primary_media:
            raise ValueError("This agent requires at least one audio or video resource.")
        if not agent.allows_context_ppt and "ppt" in kinds:
            raise ValueError("This agent does not accept PowerPoint context resources.")

    async def _dispatch_existing_job(self, job: JobRecord, *, reset_state: bool) -> JobRecord:
        dispatch_result = await self.dispatcher.dispatch(job.worker_payload)
        updated = job.model_copy(
            update={
                "status": "queued",
                "current_step": "queued",
                "progress": 0,
                "dispatch_backend": dispatch_result.backend,  # type: ignore[arg-type]
                "updated_at": utc_now_iso(),
                "next_retry_at": None,
                "completed_at": None,
                "error": None,
                "worker_state": {} if reset_state else job.worker_state,
                "azure_transcription_id": None if reset_state else job.azure_transcription_id,
                "last_attempt_started_at": utc_now_iso(),
                "last_heartbeat_at": utc_now_iso(),
            }
        )
        return await self.repository.update(updated)

    def _is_job_stale(self, job: JobRecord) -> bool:
        heartbeat_source = job.last_heartbeat_at or job.updated_at or job.created_at
        if not heartbeat_source:
            return False
        try:
            heartbeat_at = datetime.fromisoformat(heartbeat_source.replace("Z", "+00:00"))
        except ValueError:
            return False
        return heartbeat_at <= datetime.now(timezone.utc) - timedelta(
            seconds=self.settings.jobs_stale_heartbeat_seconds
        )

    def _build_artifact_records(self, job: JobRecord) -> list[JobArtifactRecord]:
        records: list[JobArtifactRecord] = []
        for key in ("transcript_json", "transcript_txt", "final_markdown", "final_json", "log_path"):
            path = job.artifacts.get(key)
            if not path:
                continue
            filename = Path(str(path)).name
            records.append(
                JobArtifactRecord(
                    artifact_key=key,
                    filename=filename,
                    content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
                    size_bytes=self._artifact_size(job, str(path)),
                    download_path=str(path),
                )
            )
        return records

    def _artifact_size(self, job: JobRecord, path: str) -> int | None:
        if job.artifacts.get("storage_backend") == "local":
            candidate = Path(path).expanduser().resolve()
            if candidate.exists():
                return candidate.stat().st_size
        return None
