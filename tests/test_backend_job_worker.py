from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from agents.shared_tools.meeting_minutes.unified_pipeline import MeetingPipelineResult
from backend.app import create_app
from backend.core.config import get_settings
from backend.core.security import EntraPrincipal, get_token_validator
from backend.http.dependencies import AuthenticatedUserContext, get_authenticated_user_context
from backend.modules.admin.models import UserAccount
from backend.modules.jobs.dispatcher import JobDispatchResult, JobDispatcher
from backend.modules.jobs.worker import MeetingJobWorker
from backend.modules.notifications.service import NotificationResult


@dataclass
class FakeDispatcher(JobDispatcher):
    calls: list[tuple[dict, int | None]] = field(default_factory=list)

    async def dispatch(self, payload: dict, *, delay_seconds: int | None = None) -> JobDispatchResult:
        self.calls.append((payload, delay_seconds))
        return JobDispatchResult(backend="service_bus", reference="fake-queue")


@dataclass
class FakeNotificationService:
    calls: list[dict] = field(default_factory=list)

    def send_job_finished_notification(self, *, user, job, final_markdown_path):
        self.calls.append(
            {
                "user_email": user.email,
                "job_id": job.job_id,
                "status": job.status,
                "final_markdown_path": final_markdown_path,
            }
        )
        return NotificationResult(status="sent", recipient=user.email, error=None)


class BackendJobWorkerTests(unittest.TestCase):
    VALID_MP4_BYTES = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    def setUp(self) -> None:
        get_settings.cache_clear()
        get_token_validator.cache_clear()
        self.tempdir = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(
            os.environ,
            {"BACKEND_LOCAL_STORAGE_PATH": self.tempdir.name},
            clear=False,
        )
        self.env_patch.start()
        get_settings.cache_clear()
        self.app = create_app()

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()
        self.env_patch.stop()
        self.tempdir.cleanup()
        get_settings.cache_clear()
        get_token_validator.cache_clear()

    @staticmethod
    async def _juridica_user_context() -> AuthenticatedUserContext:
        return AuthenticatedUserContext(
            principal=EntraPrincipal(token="token", claims={"oid": "user-oid"}, validation_mode="test"),
            user=UserAccount(
                entra_object_id="user-oid",
                email="user@example.com",
                display_name="Test User",
                enabled=True,
                allowed_agent_ids=["juridica"],
            ),
        )

    def test_worker_processes_job_and_persists_artifacts(self) -> None:
        self.app.dependency_overrides[get_authenticated_user_context] = self._juridica_user_context

        with TestClient(self.app) as client:
            resource_response = client.post(
                "/api/resources/upload",
                data={"agent_id": "juridica"},
                files={"file": ("session.mp4", self.VALID_MP4_BYTES, "video/mp4")},
            )
            self.assertEqual(resource_response.status_code, 201)
            resource_id = resource_response.json()["resource_id"]

            deploy_response = client.post(
                "/api/jobs/deploy",
                json={"agent_id": "juridica", "resource_ids": [resource_id], "options": {"variant": "auto"}},
            )
            self.assertEqual(deploy_response.status_code, 201)
            deployed_job = deploy_response.json()

            worker = MeetingJobWorker(
                settings=self.app.state.settings,
                clients=self.app.state.clients,
                job_repository=self.app.state.job_repository,
                resource_service=self.app.state.resource_service,
                admin_service=self.app.state.admin_service,
                job_dispatcher=FakeDispatcher(),
                notification_service=FakeNotificationService(),
            )

            def fake_run_meeting_pipeline(**kwargs):
                output_dir = Path(kwargs["output_dir"])
                output_dir.mkdir(parents=True, exist_ok=True)
                final_md = output_dir / "acta_juridica_final.md"
                final_json = output_dir / "acta_juridica_final.json"
                final_md.write_text("# Acta\n\nContenido final", encoding="utf-8")
                final_json.write_text(json.dumps({"status": "approved"}), encoding="utf-8")
                return MeetingPipelineResult(
                    domain="juridica",
                    input_source="transcript",
                    variant="chunk_led",
                    status="approved",
                    output_dir=str(output_dir),
                    audio_path=None,
                    transcript_path=kwargs["transcript_path"],
                    transcript_json_path=str(output_dir / "transcript.json"),
                    ppt_path=kwargs.get("ppt_path"),
                    chunk_dir=str(output_dir / "chunks"),
                    segmentation_result_path=str(output_dir / "segmentation_segments.json"),
                    segmentation_markdown_path=str(output_dir / "segmentation_segments.md"),
                    final_markdown_path=str(final_md),
                    final_json_path=str(final_json),
                    domain_result={"status": "approved"},
                )

            with (
                patch("backend.modules.jobs.worker.run_audio_pipeline", return_value=([0.0, 0.0, 0.0], 16000)),
                patch("backend.modules.jobs.worker.resolve_transcription_route", return_value="fast"),
                patch(
                    "backend.modules.jobs.worker.transcribe_audio",
                    return_value={"text": "transcript body", "continuous_text": "transcript body", "mode": "fast"},
                ),
                patch("backend.modules.jobs.worker.run_meeting_pipeline", side_effect=fake_run_meeting_pipeline),
            ):
                processed_job = asyncio.run(worker.process_payload(deployed_job["worker_payload"]))

        self.assertEqual(processed_job.status, "completed")
        self.assertEqual(processed_job.final_result_summary["status"], "approved")
        self.assertEqual(processed_job.transcript_text, "transcript body")
        self.assertIn("Contenido final", processed_job.final_result_text)
        self.assertIn("[worker]", processed_job.logs_text)
        self.assertIn("log_path", processed_job.artifacts)
        self.assertTrue(Path(processed_job.artifacts["final_markdown"]).exists())
        self.assertTrue(Path(processed_job.artifacts["transcript_txt"]).exists())
        self.assertTrue(Path(processed_job.log_summary["path"]).exists())
        self.assertEqual(processed_job.notification_status, "sent")
        self.assertEqual(processed_job.notification_recipient, "user@example.com")

    def test_worker_waits_for_batch_and_resumes(self) -> None:
        self.app.dependency_overrides[get_authenticated_user_context] = self._juridica_user_context

        with TestClient(self.app) as client:
            resource_response = client.post(
                "/api/resources/upload",
                data={"agent_id": "juridica"},
                files={"file": ("session.mp4", self.VALID_MP4_BYTES, "video/mp4")},
            )
            self.assertEqual(resource_response.status_code, 201)
            resource_id = resource_response.json()["resource_id"]

            deploy_response = client.post(
                "/api/jobs/deploy",
                json={"agent_id": "juridica", "resource_ids": [resource_id], "options": {"variant": "auto"}},
            )
            self.assertEqual(deploy_response.status_code, 201)
            deployed_job = deploy_response.json()

            dispatcher = FakeDispatcher()
            worker = MeetingJobWorker(
                settings=self.app.state.settings,
                clients=self.app.state.clients,
                job_repository=self.app.state.job_repository,
                resource_service=self.app.state.resource_service,
                admin_service=self.app.state.admin_service,
                job_dispatcher=dispatcher,
                notification_service=self.app.state.notification_service,
            )
            worker.settings.servicebus_fully_qualified_namespace = "fake.servicebus.windows.net"

            class _FakeStorage:
                def delete_blob(self, blob_name: str) -> None:
                    _ = blob_name

            def fake_run_meeting_pipeline(**kwargs):
                output_dir = Path(kwargs["output_dir"])
                output_dir.mkdir(parents=True, exist_ok=True)
                final_md = output_dir / "acta_juridica_final.md"
                final_json = output_dir / "acta_juridica_final.json"
                final_md.write_text("# Acta\n\nContenido batch final", encoding="utf-8")
                final_json.write_text(json.dumps({"status": "approved"}), encoding="utf-8")
                return MeetingPipelineResult(
                    domain="juridica",
                    input_source="transcript",
                    variant="chunk_led",
                    status="approved",
                    output_dir=str(output_dir),
                    audio_path=None,
                    transcript_path=kwargs["transcript_path"],
                    transcript_json_path=str(output_dir / "transcript.json"),
                    ppt_path=kwargs.get("ppt_path"),
                    chunk_dir=str(output_dir / "chunks"),
                    segmentation_result_path=str(output_dir / "segmentation_segments.json"),
                    segmentation_markdown_path=str(output_dir / "segmentation_segments.md"),
                    final_markdown_path=str(final_md),
                    final_json_path=str(final_json),
                    domain_result={"status": "approved"},
                )

            with (
                patch("backend.modules.jobs.worker.run_audio_pipeline", return_value=([0.0, 0.0, 0.0], 16000)),
                patch("backend.modules.jobs.worker.resolve_transcription_route", return_value="batch"),
                patch("backend.modules.jobs.worker.resolve_storage_manager", return_value=_FakeStorage()),
                patch(
                    "backend.modules.jobs.worker.submit_batch_transcription",
                    return_value={
                        "transcription_id": "tx-123",
                        "transcription_url": "https://speech.test/transcriptions/tx-123",
                        "submitted_at": datetime.now(timezone.utc).isoformat(),
                        "status": "Running",
                        "uploaded_blob": {"blob_name": "audio/blob.wav", "blob_url": "https://blob.test/audio/blob.wav"},
                    },
                ),
            ):
                waiting_job = asyncio.run(worker.process_payload(deployed_job["worker_payload"]))

            self.assertEqual(waiting_job.status, "waiting_transcription_batch")
            self.assertEqual(waiting_job.azure_transcription_id, "tx-123")
            self.assertEqual(len(dispatcher.calls), 1)
            self.assertEqual(dispatcher.calls[0][1], self.app.state.settings.servicebus_job_retry_delay_seconds)

            with (
                patch("backend.modules.jobs.worker.resolve_storage_manager", return_value=_FakeStorage()),
                patch(
                    "backend.modules.jobs.worker.get_batch_transcription_status",
                    return_value={"status": "Succeeded", "links": {"files": "https://speech.test/files"}},
                ),
                patch(
                    "backend.modules.jobs.worker.fetch_batch_transcription_result",
                    return_value={
                        "mode": "batch",
                        "text": "transcript batch body",
                        "continuous_text": "transcript batch body",
                        "final_status": {"status": "Succeeded"},
                    },
                ),
                patch("backend.modules.jobs.worker.run_meeting_pipeline", side_effect=fake_run_meeting_pipeline),
            ):
                completed_job = asyncio.run(worker.process_payload(deployed_job["worker_payload"]))

        self.assertEqual(completed_job.status, "completed")
        self.assertEqual(completed_job.transcript_text, "transcript batch body")
        self.assertIn("Contenido batch final", completed_job.final_result_text)
        self.assertEqual(completed_job.final_result_summary["status"], "approved")

    def test_worker_persists_artifacts_when_pipeline_result_omits_transcript_json_path(self) -> None:
        self.app.dependency_overrides[get_authenticated_user_context] = self._juridica_user_context

        with TestClient(self.app) as client:
            resource_response = client.post(
                "/api/resources/upload",
                data={"agent_id": "juridica"},
                files={"file": ("session.mp4", self.VALID_MP4_BYTES, "video/mp4")},
            )
            self.assertEqual(resource_response.status_code, 201)
            resource_id = resource_response.json()["resource_id"]

            deploy_response = client.post(
                "/api/jobs/deploy",
                json={"agent_id": "juridica", "resource_ids": [resource_id], "options": {"variant": "auto"}},
            )
            self.assertEqual(deploy_response.status_code, 201)
            deployed_job = deploy_response.json()

            worker = MeetingJobWorker(
                settings=self.app.state.settings,
                clients=self.app.state.clients,
                job_repository=self.app.state.job_repository,
                resource_service=self.app.state.resource_service,
                admin_service=self.app.state.admin_service,
                job_dispatcher=FakeDispatcher(),
                notification_service=FakeNotificationService(),
            )

            def fake_run_meeting_pipeline(**kwargs):
                output_dir = Path(kwargs["output_dir"])
                output_dir.mkdir(parents=True, exist_ok=True)
                final_md = output_dir / "acta_juridica_final.md"
                final_json = output_dir / "acta_juridica_final.json"
                final_md.write_text("# Acta\n\nContenido final", encoding="utf-8")
                final_json.write_text(json.dumps({"status": "approved"}), encoding="utf-8")
                return MeetingPipelineResult(
                    domain="juridica",
                    input_source="transcript",
                    variant="chunk_led",
                    status="approved",
                    output_dir=str(output_dir),
                    audio_path=None,
                    transcript_path=kwargs["transcript_path"],
                    transcript_json_path=None,
                    ppt_path=kwargs.get("ppt_path"),
                    chunk_dir=str(output_dir / "chunks"),
                    segmentation_result_path=str(output_dir / "segmentation_segments.json"),
                    segmentation_markdown_path=str(output_dir / "segmentation_segments.md"),
                    final_markdown_path=str(final_md),
                    final_json_path=str(final_json),
                    domain_result={"status": "approved"},
                )

            with (
                patch("backend.modules.jobs.worker.run_audio_pipeline", return_value=([0.0, 0.0, 0.0], 16000)),
                patch(
                    "backend.modules.jobs.worker.transcribe_audio",
                    return_value={"text": "transcript body", "continuous_text": "transcript body", "mode": "fast"},
                ),
                patch("backend.modules.jobs.worker.resolve_transcription_route", return_value="fast"),
                patch("backend.modules.jobs.worker.run_meeting_pipeline", side_effect=fake_run_meeting_pipeline),
            ):
                processed_job = asyncio.run(worker.process_payload(deployed_job["worker_payload"]))

        self.assertEqual(processed_job.status, "completed")
        self.assertTrue(Path(processed_job.artifacts["transcript_json"]).exists())
        self.assertTrue(Path(processed_job.artifacts["transcript_txt"]).exists())


if __name__ == "__main__":
    unittest.main()
