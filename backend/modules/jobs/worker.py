from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import soundfile as sf

from agents.shared_tools.meeting_minutes.media_pipeline import (
    DEFAULT_TRANSCRIPTION_TARGET_SR,
    resolve_storage_manager,
)
from agents.shared_tools.meeting_minutes.unified_pipeline import MeetingPipelineResult, run_meeting_pipeline
from audio_tools.azure.transcript import (
    fetch_batch_transcription_result,
    get_batch_transcription_status,
    resolve_transcription_route,
    submit_batch_transcription,
    transcribe_audio,
    transcript_to_continuous_text,
)
from audio_tools.prepare_audio import run_audio_pipeline
from backend.core.config import Settings
from backend.infra.clients import AppClients
from backend.modules.jobs.dispatcher import JobDispatcher, create_job_dispatcher
from backend.modules.jobs.models import JobRecord, JobStepRecord
from backend.modules.jobs.repository import JobRepository
from backend.modules.admin.models import UserAccount
from backend.modules.notifications import NotificationService, create_notification_service
from backend.modules.resources.models import ResourceRecord
from backend.modules.resources.service import ResourceService
from backend.modules.admin.service import AdminService


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True)
class WorkerPaths:
    job_root: Path
    inputs_dir: Path
    output_dir: Path
    logs_dir: Path
    log_path: Path
    prepared_audio_path: Path
    transcript_text_path: Path
    transcript_json_path: Path


class MeetingJobWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        clients: AppClients,
        job_repository: JobRepository,
        resource_service: ResourceService,
        admin_service: AdminService,
        job_dispatcher: JobDispatcher | None = None,
        notification_service: NotificationService | None = None,
    ) -> None:
        self.settings = settings
        self.clients = clients
        self.job_repository = job_repository
        self.resource_service = resource_service
        self.admin_service = admin_service
        self.job_dispatcher = job_dispatcher or create_job_dispatcher(settings, clients)
        self.notification_service = notification_service or create_notification_service(settings)

    async def process_payload(self, payload: dict[str, Any]) -> JobRecord:
        owner_object_id = payload["owner_object_id"]
        job_id = payload["job_id"]
        job = await self.job_repository.get(owner_object_id, job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")
        if job.status in {"completed", "dead_lettered", "canceled"}:
            return job

        paths = self._build_paths(job_id)
        paths.logs_dir.mkdir(parents=True, exist_ok=True)
        paths.inputs_dir.mkdir(parents=True, exist_ok=True)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        self._emit_log(paths.log_path, "job_received", job_id=job.job_id, status=job.status)

        try:
            resources = [ResourceRecord.model_validate(item) for item in payload["resources"]]
            if job.status == "queued":
                job = await self._mark_step(job, "validating", "running", "Worker accepted job.", progress=5)
                job = await self._mark_step(job, "validating", "completed", "Worker accepted job.", progress=10)

            if job.status not in {"waiting_transcription_batch"}:
                job = await self._mark_step(
                    job,
                    "downloading_resources",
                    "running",
                    "Downloading resource set.",
                    progress=15,
                )
            local_resources = await self._download_resources(resources, paths.inputs_dir)
            media_path, ppt_path = self._resolve_pipeline_inputs(local_resources)
            if job.status not in {"waiting_transcription_batch"}:
                job = await self._mark_step(
                    job,
                    "downloading_resources",
                    "completed",
                    "Resource set downloaded.",
                    progress=25,
                )

            transcript_ready = await self._ensure_transcript(
                job=job,
                media_path=media_path,
                paths=paths,
            )
            if transcript_ready is None:
                waiting_job = await self.job_repository.get(owner_object_id, job_id)
                if waiting_job is None:
                    raise ValueError(f"Job not found after waiting transition: {job_id}")
                return waiting_job
            job = transcript_ready

            job = await self._mark_step(
                job,
                "running_agent",
                "running",
                "Executing segmentation and domain agent pipeline.",
                progress=70,
            )
            pipeline_result = await self._run_pipeline(
                job=job,
                transcript_path=str(paths.transcript_text_path),
                ppt_path=ppt_path,
                output_dir=paths.output_dir,
                log_path=paths.log_path,
            )
            job = await self._mark_step(
                job,
                "running_agent",
                "completed",
                "Pipeline execution completed.",
                progress=85,
            )
            job = await self._mark_step(
                job,
                "uploading_artifacts",
                "running",
                "Persisting outputs and logs.",
                progress=90,
            )
            artifact_paths = await self._persist_artifacts(job, pipeline_result, paths)

            current_log_text = self._read_text_if_exists(paths.log_path) or ""
            merged_logs = self._merge_logs(job.logs_text, current_log_text)
            final_job = job.model_copy(
                update={
                    "status": "completed",
                    "current_step": "completed",
                    "progress": 100,
                    "artifacts": artifact_paths,
                    "transcript_summary": self._build_transcript_summary(paths.transcript_text_path),
                    "final_result_summary": self._build_final_result_summary(pipeline_result),
                    "log_summary": self._build_log_summary(paths.log_path),
                    "transcript_text": self._read_text_if_exists(paths.transcript_text_path),
                    "final_result_text": self._read_text_if_exists(Path(pipeline_result.final_markdown_path)),
                    "logs_text": merged_logs,
                    "completed_at": utc_now_iso(),
                    "updated_at": utc_now_iso(),
                    "next_retry_at": None,
                    "last_heartbeat_at": utc_now_iso(),
                    "pipeline_steps": self._replace_step(
                        job.pipeline_steps,
                        JobStepRecord(
                            name="uploading_artifacts",
                            status="completed",
                            message="Artifacts persisted.",
                            started_at=self._find_step_started_at(job.pipeline_steps, "uploading_artifacts"),
                            finished_at=utc_now_iso(),
                        ),
                    ),
                }
            )
            final_job = await self.job_repository.update(final_job)
            return await self._notify_terminal_state(final_job, final_markdown_path=pipeline_result.final_markdown_path)
        except Exception as exc:
            trace = traceback.format_exc()
            self._emit_log(
                paths.log_path,
                "job_exception",
                job_id=job.job_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            if paths.log_path.parent.exists():
                with paths.log_path.open("a", encoding="utf-8") as handle:
                    handle.write("\n[worker.exception]\n")
                    handle.write(trace)
            pipeline_steps = job.pipeline_steps
            if job.current_step and job.current_step != "completed":
                pipeline_steps = self._replace_step(
                    job.pipeline_steps,
                    JobStepRecord(
                        name=job.current_step,
                        status="failed",
                        message=str(exc),
                        started_at=self._find_step_started_at(job.pipeline_steps, job.current_step) or utc_now_iso(),
                        finished_at=utc_now_iso(),
                    ),
                )
            attempt_count = job.attempt_count + 1
            should_retry = attempt_count < job.max_attempts and self.settings.servicebus_enabled
            now = utc_now_iso()
            updated_job = job.model_copy(
                update={
                    "status": "queued" if should_retry else "dead_lettered",
                    "current_step": "queued" if should_retry else "dead_lettered",
                    "attempt_count": attempt_count,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                    "log_summary": self._build_log_summary(paths.log_path),
                    "logs_text": self._merge_logs(job.logs_text, self._read_text_if_exists(paths.log_path)),
                    "updated_at": now,
                    "completed_at": None if should_retry else now,
                    "next_retry_at": (
                        (datetime.now(timezone.utc) + timedelta(seconds=self.settings.servicebus_job_retry_delay_seconds))
                        .replace(microsecond=0)
                        .isoformat()
                        if should_retry
                        else None
                    ),
                    "last_heartbeat_at": now,
                    "pipeline_steps": pipeline_steps,
                }
            )
            updated_job = await self.job_repository.update(updated_job)
            if should_retry:
                await self._schedule_retry(job_payload=job.worker_payload)
                return updated_job
            return await self._notify_terminal_state(updated_job, final_markdown_path=None)

    async def _ensure_transcript(
        self,
        *,
        job: JobRecord,
        media_path: str,
        paths: WorkerPaths,
    ) -> JobRecord | None:
        if paths.transcript_text_path.exists() and paths.transcript_json_path.exists():
            return job

        batch_url = str(job.worker_state.get("batch_transcription_url") or "")
        if batch_url:
            return await self._resume_batch_transcription(job=job, paths=paths)

        job = await self._mark_step(
            job,
            "preparing_audio",
            "running",
            "Preparing enhanced audio for transcription.",
            progress=30,
        )
        audio, sample_rate, job = await self._run_audio_preparation(
            job=job,
            media_path=media_path,
            paths=paths,
        )
        paths.prepared_audio_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(paths.prepared_audio_path, audio, sample_rate)
        job = await self._mark_step(
            job,
            "preparing_audio",
            "completed",
            "Prepared audio saved.",
            progress=40,
        )

        route = resolve_transcription_route(
            str(paths.prepared_audio_path),
            route_filename=paths.prepared_audio_path.name,
        )
        if route == "fast":
            return await self._run_fast_transcription(job=job, prepared_audio_path=paths.prepared_audio_path, paths=paths)

        return await self._submit_batch_transcription(job=job, prepared_audio_path=paths.prepared_audio_path, paths=paths)

    async def _run_fast_transcription(
        self,
        *,
        job: JobRecord,
        prepared_audio_path: Path,
        paths: WorkerPaths,
    ) -> JobRecord:
        job = await self._mark_step(
            job,
            "transcribing",
            "running",
            "Running fast Azure Speech transcription.",
            progress=45,
        )
        transcript = await asyncio.to_thread(
            transcribe_audio,
            str(prepared_audio_path),
            route_filename=prepared_audio_path.name,
        )
        self._write_transcript_files(transcript, paths)
        return await self._mark_step(
            job,
            "transcribing",
            "completed",
            "Fast transcription completed.",
            progress=60,
        )

    async def _run_audio_preparation(
        self,
        *,
        job: JobRecord,
        media_path: str,
        paths: WorkerPaths,
    ) -> tuple[Any, int, JobRecord]:
        progress_state: dict[str, str] = {
            "message": "Preparing enhanced audio for transcription.",
        }
        current_job = job

        def progress_callback(event: str, payload: dict[str, Any] | None = None) -> None:
            message = self._render_audio_prep_message(event, payload)
            progress_state["message"] = message
            self._emit_log(
                paths.log_path,
                "audio_prep_progress",
                job_id=job.job_id,
                progress_event=event,
                message=message,
                **(payload or {}),
            )

        async def heartbeat_loop() -> None:
            nonlocal current_job
            while True:
                await asyncio.sleep(15)
                now = utc_now_iso()
                message = progress_state["message"]
                current_job = current_job.model_copy(
                    update={
                        "last_heartbeat_at": now,
                        "updated_at": now,
                        "pipeline_steps": self._replace_step(
                            current_job.pipeline_steps,
                            JobStepRecord(
                                name="preparing_audio",
                                status="running",
                                message=message,
                                started_at=self._find_step_started_at(
                                    current_job.pipeline_steps,
                                    "preparing_audio",
                                )
                                or now,
                                finished_at=None,
                            ),
                        ),
                    }
                )
                current_job = await self.job_repository.update(current_job)
                self._emit_log(
                    paths.log_path,
                    "audio_prep_heartbeat",
                    job_id=job.job_id,
                    message=message,
                )

        heartbeat_task = asyncio.create_task(heartbeat_loop())
        try:
            audio, sample_rate = await asyncio.to_thread(
                run_audio_pipeline,
                media_path,
                DEFAULT_TRANSCRIPTION_TARGET_SR,
                True,
                progress_callback,
            )
            return audio, sample_rate, current_job
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _submit_batch_transcription(
        self,
        *,
        job: JobRecord,
        prepared_audio_path: Path,
        paths: WorkerPaths,
    ) -> None:
        storage_manager = resolve_storage_manager()
        if storage_manager is None:
            raise ValueError(
                "Azure batch transcription requires Blob Storage configuration in the worker environment."
            )

        job = await self._mark_step(
            job,
            "transcribing",
            "running",
            "Submitting Azure batch transcription job.",
            progress=45,
        )
        submission = await asyncio.to_thread(
            submit_batch_transcription,
            str(prepared_audio_path),
            storage_manager=storage_manager,
            route_filename=prepared_audio_path.name,
        )
        waiting_step = JobStepRecord(
            name="waiting_transcription_batch",
            status="running",
            message="Waiting for Azure Speech batch transcription to finish.",
            started_at=utc_now_iso(),
            finished_at=None,
        )
        updated_job = job.model_copy(
            update={
                "status": "waiting_transcription_batch",
                "current_step": "waiting_transcription_batch",
                "progress": 50,
                "azure_transcription_id": submission["transcription_id"],
                "worker_state": {
                    **job.worker_state,
                    "transcription_route": "batch",
                    "batch_transcription_url": submission["transcription_url"],
                    "batch_submitted_at": submission["submitted_at"] or utc_now_iso(),
                    "batch_last_status": submission.get("status") or "NotStarted",
                    "uploaded_blob_name": submission["uploaded_blob"]["blob_name"],
                    "uploaded_blob_url": submission["uploaded_blob"]["blob_url"],
                    "prepared_audio_filename": prepared_audio_path.name,
                },
                "logs_text": self._merge_logs(job.logs_text, self._read_text_if_exists(paths.log_path)),
                "log_summary": self._build_log_summary(paths.log_path),
                "updated_at": utc_now_iso(),
                "last_heartbeat_at": utc_now_iso(),
                "pipeline_steps": self._replace_step(
                    self._replace_step(
                        job.pipeline_steps,
                        JobStepRecord(
                            name="transcribing",
                            status="running",
                            message=f"Batch transcription submitted: {submission['transcription_id']}.",
                            started_at=self._find_step_started_at(job.pipeline_steps, "transcribing") or utc_now_iso(),
                            finished_at=None,
                        ),
                    ),
                    waiting_step,
                ),
            }
        )
        await self.job_repository.update(updated_job)
        await self._schedule_retry(job_payload=job.worker_payload)
        return None

    async def _resume_batch_transcription(
        self,
        *,
        job: JobRecord,
        paths: WorkerPaths,
    ) -> JobRecord | None:
        transcription_url = str(job.worker_state.get("batch_transcription_url") or "")
        if not transcription_url:
            raise ValueError("Missing batch_transcription_url in worker state.")

        submitted_at = _parse_iso_datetime(str(job.worker_state.get("batch_submitted_at") or "")) or _parse_iso_datetime(job.started_at)
        if submitted_at is not None:
            max_wait = timedelta(hours=float(self.settings.azure_batch_max_wait_hours))
            if datetime.now(timezone.utc) - submitted_at > max_wait:
                raise TimeoutError(
                    f"Azure batch transcription exceeded the configured wait window of {self.settings.azure_batch_max_wait_hours} hours."
                )

        status_payload = await asyncio.to_thread(
            get_batch_transcription_status,
            transcription_url,
        )
        batch_status = str(status_payload.get("status") or "Unknown")

        if batch_status in {"NotStarted", "Running"}:
            updated_job = job.model_copy(
                update={
                    "status": "waiting_transcription_batch",
                    "current_step": "waiting_transcription_batch",
                    "progress": 50,
                    "logs_text": self._merge_logs(job.logs_text, self._read_text_if_exists(paths.log_path)),
                    "log_summary": self._build_log_summary(paths.log_path),
                    "updated_at": utc_now_iso(),
                    "last_heartbeat_at": utc_now_iso(),
                    "worker_state": {
                        **job.worker_state,
                        "batch_last_status": batch_status,
                        "batch_last_polled_at": utc_now_iso(),
                    },
                    "pipeline_steps": self._replace_step(
                        job.pipeline_steps,
                        JobStepRecord(
                            name="waiting_transcription_batch",
                            status="running",
                            message=f"Azure batch status: {batch_status}.",
                            started_at=self._find_step_started_at(job.pipeline_steps, "waiting_transcription_batch") or utc_now_iso(),
                            finished_at=None,
                        ),
                    ),
                }
            )
            await self.job_repository.update(updated_job)
            await self._schedule_retry(job_payload=job.worker_payload)
            return None

        if batch_status == "Failed":
            raise RuntimeError(f"Azure batch transcription failed: {json.dumps(status_payload, ensure_ascii=True)}")

        transcript = await asyncio.to_thread(
            fetch_batch_transcription_result,
            transcription_url,
        )
        self._write_transcript_files(transcript, paths)
        self._cleanup_uploaded_batch_blob(job)

        updated_job = job.model_copy(
            update={
                "progress": 60,
                "updated_at": utc_now_iso(),
                "last_heartbeat_at": utc_now_iso(),
                "worker_state": {
                    **{k: v for k, v in job.worker_state.items() if k not in {"batch_transcription_url", "uploaded_blob_name"}},
                    "batch_last_status": batch_status,
                    "batch_completed_at": utc_now_iso(),
                },
                "pipeline_steps": self._replace_step(
                    self._replace_step(
                        job.pipeline_steps,
                        JobStepRecord(
                            name="waiting_transcription_batch",
                            status="completed",
                            message="Azure batch transcription completed.",
                            started_at=self._find_step_started_at(job.pipeline_steps, "waiting_transcription_batch") or utc_now_iso(),
                            finished_at=utc_now_iso(),
                        ),
                    ),
                    JobStepRecord(
                        name="transcribing",
                        status="completed",
                        message="Batch transcription completed.",
                        started_at=self._find_step_started_at(job.pipeline_steps, "transcribing") or utc_now_iso(),
                        finished_at=utc_now_iso(),
                    ),
                ),
            }
        )
        return await self.job_repository.update(updated_job)

    async def _run_pipeline(
        self,
        *,
        job: JobRecord,
        transcript_path: str,
        ppt_path: str | None,
        output_dir: Path,
        log_path: Path,
    ) -> MeetingPipelineResult:
        def _runner() -> MeetingPipelineResult:
            output_dir.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as log_handle:
                log_handle.write(f"[worker] job_id={job.job_id} continuing pipeline from transcript\n")
                with redirect_stdout(log_handle), redirect_stderr(log_handle):
                    return run_meeting_pipeline(
                        domain=job.agent_id,  # type: ignore[arg-type]
                        transcript_path=transcript_path,
                        ppt_path=ppt_path,
                        output_dir=output_dir,
                        variant=job.worker_payload.get("options", {}).get("variant", "auto"),
                    )

        return await asyncio.to_thread(_runner)

    async def _download_resources(self, resources: list[ResourceRecord], destination_dir: Path) -> dict[str, str]:
        downloaded: dict[str, str] = {}
        for record in resources:
            local_path = await self.resource_service.download_resource_to_directory(
                record=record,
                destination_dir=destination_dir / record.resource_id,
            )
            downloaded[record.resource_id] = local_path
        return downloaded

    def _resolve_pipeline_inputs(self, local_resources: dict[str, str]) -> tuple[str, str | None]:
        media_path = None
        ppt_path = None
        for local_path in local_resources.values():
            suffix = Path(local_path).suffix.lower()
            if suffix in {".ppt", ".pptx"}:
                ppt_path = local_path
            else:
                media_path = local_path
        if media_path is None:
            raise ValueError("No audio or video resource was provided for the job.")
        return media_path, ppt_path

    async def _persist_artifacts(
        self,
        job: JobRecord,
        pipeline_result: MeetingPipelineResult,
        paths: WorkerPaths,
    ) -> dict[str, Any]:
        if self.clients.blob_service_client is not None and self.settings.blob_enabled:
            return await self._persist_artifacts_to_blob(job.job_id, paths, pipeline_result)
        return self._persist_artifacts_to_local(job.job_id, paths, pipeline_result)

    def _persist_artifacts_to_local(
        self,
        job_id: str,
        paths: WorkerPaths,
        pipeline_result: MeetingPipelineResult,
    ) -> dict[str, Any]:
        output_dir = paths.output_dir
        artifact_root = Path(self.settings.local_storage_path).expanduser().resolve() / "artifacts" / "jobs" / job_id
        if artifact_root.exists():
            shutil.rmtree(artifact_root)
        shutil.copytree(output_dir, artifact_root)
        logs_dir = artifact_root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(paths.log_path, logs_dir / paths.log_path.name)
        return self._artifact_payload(
            artifact_root=artifact_root,
            worker_paths=paths,
            pipeline_result=pipeline_result,
            log_target=logs_dir / paths.log_path.name,
        )

    async def _persist_artifacts_to_blob(
        self,
        job_id: str,
        paths: WorkerPaths,
        pipeline_result: MeetingPipelineResult,
    ) -> dict[str, Any]:
        container = self.settings.blob_artifacts_container_name
        output_dir = paths.output_dir
        uploaded: dict[str, str] = {}
        for path in [item for item in output_dir.rglob("*") if item.is_file()]:
            relative = path.relative_to(output_dir).as_posix()
            blob_name = f"jobs/{job_id}/{relative}"
            blob_client = self.clients.blob_service_client.get_blob_client(container=container, blob=blob_name)
            await blob_client.upload_blob(path.read_bytes(), overwrite=True)
            uploaded[relative] = blob_name

        log_blob_name = f"jobs/{job_id}/logs/{paths.log_path.name}"
        blob_client = self.clients.blob_service_client.get_blob_client(container=container, blob=log_blob_name)
        await blob_client.upload_blob(paths.log_path.read_bytes(), overwrite=True)

        return {
            "storage_backend": "blob",
            "root": f"{container}/jobs/{job_id}",
            "transcript_json": self._resolve_uploaded_artifact_path(
                uploaded,
                output_dir=output_dir,
                preferred_path=pipeline_result.transcript_json_path,
                fallback_path=paths.transcript_json_path,
            ),
            "transcript_txt": self._resolve_uploaded_artifact_path(
                uploaded,
                output_dir=output_dir,
                preferred_path=pipeline_result.transcript_path,
                fallback_path=paths.transcript_text_path,
            ),
            "final_markdown": self._resolve_uploaded_artifact_path(
                uploaded,
                output_dir=output_dir,
                preferred_path=pipeline_result.final_markdown_path,
            ),
            "final_json": self._resolve_uploaded_artifact_path(
                uploaded,
                output_dir=output_dir,
                preferred_path=pipeline_result.final_json_path,
            ),
            "log_path": log_blob_name,
            "files": uploaded,
        }

    def _artifact_payload(
        self,
        *,
        artifact_root: Path,
        worker_paths: WorkerPaths,
        pipeline_result: MeetingPipelineResult,
        log_target: Path,
    ) -> dict[str, Any]:
        file_index = {}
        for path in artifact_root.rglob("*"):
            if path.is_file():
                file_index[path.relative_to(artifact_root).as_posix()] = str(path)
        return {
            "storage_backend": "local",
            "root": str(artifact_root),
            "transcript_json": self._resolve_local_artifact_path(
                artifact_root=artifact_root,
                preferred_path=pipeline_result.transcript_json_path,
                fallback_path=worker_paths.transcript_json_path,
            ),
            "transcript_txt": self._resolve_local_artifact_path(
                artifact_root=artifact_root,
                preferred_path=pipeline_result.transcript_path,
                fallback_path=worker_paths.transcript_text_path,
            ),
            "final_markdown": self._resolve_local_artifact_path(
                artifact_root=artifact_root,
                preferred_path=pipeline_result.final_markdown_path,
            ),
            "final_json": self._resolve_local_artifact_path(
                artifact_root=artifact_root,
                preferred_path=pipeline_result.final_json_path,
            ),
            "log_path": str(log_target),
            "files": file_index,
        }

    def _resolve_uploaded_artifact_path(
        self,
        uploaded: dict[str, str],
        *,
        output_dir: Path,
        preferred_path: str | None,
        fallback_path: Path | None = None,
    ) -> str | None:
        candidate = self._resolve_candidate_path(preferred_path, fallback_path)
        if candidate is None:
            return None
        try:
            relative = candidate.relative_to(output_dir).as_posix()
        except ValueError:
            relative = candidate.name
        return uploaded.get(relative) or uploaded.get(candidate.name) or str(candidate)

    def _resolve_local_artifact_path(
        self,
        *,
        artifact_root: Path,
        preferred_path: str | None,
        fallback_path: Path | None = None,
    ) -> str | None:
        candidate = self._resolve_candidate_path(preferred_path, fallback_path)
        if candidate is None:
            return None
        return str(artifact_root / candidate.name)

    def _resolve_candidate_path(self, preferred_path: str | None, fallback_path: Path | None = None) -> Path | None:
        if preferred_path:
            return Path(preferred_path)
        if fallback_path is not None:
            return fallback_path
        return None

    async def _schedule_retry(self, *, job_payload: dict[str, Any]) -> None:
        if self.settings.servicebus_enabled:
            await self.job_dispatcher.dispatch(
                job_payload,
                delay_seconds=self.settings.servicebus_job_retry_delay_seconds,
            )

    async def _mark_step(
        self,
        job: JobRecord,
        step_name: str,
        step_status: str,
        message: str,
        *,
        progress: int,
    ) -> JobRecord:
        now = utc_now_iso()
        existing_started_at = self._find_step_started_at(job.pipeline_steps, step_name) or now
        step = JobStepRecord(
            name=step_name,
            status=step_status,  # type: ignore[arg-type]
            message=message,
            started_at=existing_started_at,
            finished_at=None if step_status == "running" else now,
        )
        updated = job.model_copy(
            update={
                "status": self._map_step_to_job_status(step_name, step_status),
                "current_step": step_name,
                "progress": progress,
                "started_at": job.started_at or now,
                "last_attempt_started_at": job.last_attempt_started_at or now,
                "last_heartbeat_at": now,
                "updated_at": now,
                "pipeline_steps": self._replace_step(job.pipeline_steps, step),
            }
        )
        self._emit_log(
            self._build_paths(job.job_id).log_path,
            "step_update",
            job_id=job.job_id,
            step=step_name,
            step_status=step_status,
            progress=progress,
            message=message,
        )
        return await self.job_repository.update(updated)

    def _replace_step(self, steps: list[JobStepRecord], new_step: JobStepRecord) -> list[JobStepRecord]:
        replaced = [step for step in steps if step.name != new_step.name]
        replaced.append(new_step)
        return replaced

    def _find_step_started_at(self, steps: list[JobStepRecord], step_name: str) -> str | None:
        for step in steps:
            if step.name == step_name:
                return step.started_at
        return None

    def _map_step_to_job_status(self, step_name: str, step_status: str) -> str:
        if step_status == "failed":
            return "failed"
        mapping = {
            "validating": "validating",
            "downloading_resources": "downloading_resources",
            "preparing_audio": "preparing_audio",
            "transcribing": "transcribing",
            "waiting_transcription_batch": "waiting_transcription_batch",
            "running_agent": "running_agent",
            "uploading_artifacts": "uploading_artifacts",
        }
        return mapping.get(step_name, "queued")

    def _render_audio_prep_message(self, event: str, payload: dict[str, Any] | None) -> str:
        data = payload or {}
        if event == "load_audio_started":
            return "Abriendo el archivo multimedia."
        if event == "video_detected":
            return "Detectamos un video y vamos a extraer el audio."
        if event == "ffmpeg_check_started":
            return "Verificando FFmpeg para extraer audio."
        if event == "extract_audio_started":
            return "Extrayendo audio del video."
        if event == "extract_audio_completed":
            return "Audio extraído; preparando mejora."
        if event == "audio_detected":
            return "Archivo de audio detectado; preparando mejora."
        if event == "audio_loaded":
            return "Audio cargado en memoria."
        if event == "audio_loaded_for_processing":
            return "Audio listo para la etapa de mejora."
        if event == "enhancement_mode_selected":
            mode = data.get("mode")
            if mode == "light":
                return "El audio es largo; aplicando mejora liviana para evitar bloqueos."
            return "Aplicando mejora completa al audio."
        if event == "noise_reduction_started":
            return "Ejecutando reducción de ruido."
        if event == "noise_reduction_completed":
            return "Reducción de ruido terminada."
        if event == "pedalboard_started":
            return "Aplicando cadena final de mejora."
        if event == "pedalboard_completed":
            return "Cadena final de mejora completada."
        if event == "audio_pipeline_completed":
            return "Preparación de audio finalizada."
        if event == "load_audio_failed":
            return f"Falló la carga del audio: {data.get('error', 'error desconocido')}."
        return "Preparando enhanced audio para transcripción."

    def _build_paths(self, job_id: str) -> WorkerPaths:
        base_dir = Path(self.settings.local_storage_path).expanduser().resolve() / "worker_jobs" / job_id
        output_dir = base_dir / "output"
        return WorkerPaths(
            job_root=base_dir,
            inputs_dir=base_dir / "inputs",
            output_dir=output_dir,
            logs_dir=base_dir / "logs",
            log_path=base_dir / "logs" / "worker.log",
            prepared_audio_path=output_dir / "prepared_audio.wav",
            transcript_text_path=output_dir / "transcript.txt",
            transcript_json_path=output_dir / "transcript.json",
        )

    def _write_transcript_files(self, transcript: dict[str, Any], paths: WorkerPaths) -> None:
        continuous_text = transcript.get("continuous_text") or transcript_to_continuous_text(transcript)
        paths.transcript_json_path.parent.mkdir(parents=True, exist_ok=True)
        paths.transcript_json_path.write_text(
            json.dumps(transcript, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        paths.transcript_text_path.write_text(continuous_text, encoding="utf-8")

    def _cleanup_uploaded_batch_blob(self, job: JobRecord) -> None:
        blob_name = job.worker_state.get("uploaded_blob_name")
        if not blob_name:
            return
        storage_manager = resolve_storage_manager()
        if storage_manager is None:
            return
        try:
            storage_manager.delete_blob(str(blob_name))
        except Exception:
            return

    def _build_transcript_summary(self, transcript_path: Path) -> dict[str, Any]:
        text = transcript_path.read_text(encoding="utf-8") if transcript_path.exists() else ""
        return {
            "path": str(transcript_path),
            "chars": len(text),
            "preview": text[:500],
        }

    def _build_final_result_summary(self, pipeline_result: MeetingPipelineResult) -> dict[str, Any]:
        final_markdown_path = Path(pipeline_result.final_markdown_path)
        text = final_markdown_path.read_text(encoding="utf-8") if final_markdown_path.exists() else ""
        return {
            "path": pipeline_result.final_markdown_path,
            "status": pipeline_result.status,
            "preview": text[:1000],
        }

    def _build_log_summary(self, log_path: Path) -> dict[str, Any]:
        if not log_path.exists():
            return {"path": str(log_path), "preview": "", "tail": []}
        content = log_path.read_text(encoding="utf-8")
        lines = [line for line in content.splitlines() if line.strip()]
        return {
            "path": str(log_path),
            "preview": content[:1000],
            "tail": lines[-20:],
        }

    def _read_text_if_exists(self, path: Path) -> str | None:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def _merge_logs(self, previous: str | None, current: str | None) -> str | None:
        previous_text = previous or ""
        current_text = current or ""
        if not previous_text:
            return current_text or None
        if not current_text:
            return previous_text
        return f"{previous_text.rstrip()}\n\n{current_text.lstrip()}"

    async def _notify_terminal_state(self, job: JobRecord, *, final_markdown_path: str | None) -> JobRecord:
        user = await self.admin_service.get_user(job.owner_object_id)
        if user is None:
            owner_email = job.worker_payload.get("owner_email")
            owner_display_name = job.worker_payload.get("owner_display_name")
            if owner_email:
                user = UserAccount(
                    entra_object_id=job.owner_object_id,
                    email=str(owner_email),
                    display_name=None if owner_display_name is None else str(owner_display_name),
                    enabled=True,
                    allowed_agent_ids=[job.agent_id],
                )
            else:
                updated = job.model_copy(
                    update={
                        "notification_status": "skipped",
                        "notification_error": "Owner user was not found.",
                        "updated_at": utc_now_iso(),
                    }
                )
                return await self.job_repository.update(updated)

        try:
            result = await asyncio.to_thread(
                self.notification_service.send_job_finished_notification,
                user=user,
                job=job,
                final_markdown_path=final_markdown_path,
            )
        except Exception as exc:
            updated = job.model_copy(
                update={
                    "notification_status": "failed",
                    "notification_recipient": user.email,
                    "notification_error": str(exc),
                    "updated_at": utc_now_iso(),
                }
            )
            return await self.job_repository.update(updated)

        updated = job.model_copy(
            update={
                "notification_status": result.status,
                "notification_recipient": result.recipient,
                "notification_error": result.error,
                "notification_sent_at": utc_now_iso() if result.status == "sent" else None,
                "updated_at": utc_now_iso(),
            }
        )
        return await self.job_repository.update(updated)

    def _emit_log(self, log_path: Path, event: str, **payload: Any) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": utc_now_iso(),
            "event": event,
            **payload,
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True))
            handle.write("\n")
