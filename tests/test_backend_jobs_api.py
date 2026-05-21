from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import get_settings
from backend.core.security import EntraPrincipal, get_token_validator
from backend.http.dependencies import AuthenticatedUserContext, get_authenticated_user_context
from backend.modules.admin.models import UserAccount
from backend.modules.jobs.models import JobRecord


class BackendJobsApiTests(unittest.TestCase):
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

    @staticmethod
    async def _other_user_context() -> AuthenticatedUserContext:
        return AuthenticatedUserContext(
            principal=EntraPrincipal(token="token", claims={"oid": "other-oid"}, validation_mode="test"),
            user=UserAccount(
                entra_object_id="other-oid",
                email="other@example.com",
                display_name="Other User",
                enabled=True,
                allowed_agent_ids=["juridica"],
            ),
        )

    def _upload_media(self, client: TestClient, agent_id: str = "juridica") -> str:
        response = client.post(
            "/api/resources/upload",
            data={"agent_id": agent_id},
            files={"file": ("session.mp4", self.VALID_MP4_BYTES, "video/mp4")},
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["resource_id"]

    def test_user_can_deploy_job_and_read_it(self) -> None:
        self.app.dependency_overrides[get_authenticated_user_context] = self._juridica_user_context

        with TestClient(self.app) as client:
            resource_id = self._upload_media(client)
            deploy_response = client.post(
                "/api/jobs/deploy",
                json={
                    "agent_id": "juridica",
                    "resource_ids": [resource_id],
                    "options": {"variant": "auto"},
                },
            )
            jobs_response = client.get("/api/jobs")

        self.assertEqual(deploy_response.status_code, 201)
        payload = deploy_response.json()
        self.assertEqual(payload["agent_id"], "juridica")
        self.assertEqual(payload["job_tag"], "juridica")
        self.assertEqual(payload["status"], "queued")
        self.assertIn("resources", payload["worker_payload"])
        self.assertEqual(jobs_response.status_code, 200)
        self.assertEqual(len(jobs_response.json()), 1)

    def test_job_deploy_rejects_wrong_agent_for_selected_resource(self) -> None:
        self.app.dependency_overrides[get_authenticated_user_context] = self._juridica_user_context

        with TestClient(self.app) as client:
            resource_id = self._upload_media(client)
            response = client.post(
                "/api/jobs/deploy",
                json={
                    "agent_id": "compras",
                    "resource_ids": [resource_id],
                    "options": {},
                },
            )

        self.assertEqual(response.status_code, 403)

    def test_user_cannot_fetch_another_users_job(self) -> None:
        self.app.dependency_overrides[get_authenticated_user_context] = self._juridica_user_context
        with TestClient(self.app) as client:
            resource_id = self._upload_media(client)
            deploy_response = client.post(
                "/api/jobs/deploy",
                json={
                    "agent_id": "juridica",
                    "resource_ids": [resource_id],
                    "options": {},
                },
            )
        job_id = deploy_response.json()["job_id"]

        self.app.dependency_overrides[get_authenticated_user_context] = self._other_user_context
        with TestClient(self.app) as client:
            response = client.get(f"/api/jobs/{job_id}")

        self.assertEqual(response.status_code, 404)

    def test_user_can_list_and_download_job_artifacts(self) -> None:
        self.app.dependency_overrides[get_authenticated_user_context] = self._juridica_user_context

        with TestClient(self.app) as client:
            resource_id = self._upload_media(client)
            deploy_response = client.post(
                "/api/jobs/deploy",
                json={"agent_id": "juridica", "resource_ids": [resource_id], "options": {}},
            )
            job_payload = deploy_response.json()
            artifact_root = Path(self.tempdir.name) / "artifacts-fixture"
            artifact_root.mkdir(parents=True, exist_ok=True)
            transcript_path = artifact_root / "transcript.txt"
            transcript_path.write_text("hola", encoding="utf-8")
            log_path = artifact_root / "worker.log"
            log_path.write_text('{"event":"x"}\n', encoding="utf-8")
            record = JobRecord.model_validate(
                {
                    **job_payload,
                    "status": "completed",
                    "current_step": "completed",
                    "artifacts": {
                        "storage_backend": "local",
                        "transcript_txt": str(transcript_path),
                        "log_path": str(log_path),
                    },
                }
            )
            asyncio.run(self.app.state.job_repository.update(record))

            list_response = client.get(f"/api/jobs/{record.job_id}/artifacts")
            download_response = client.get(f"/api/jobs/{record.job_id}/artifacts/transcript_txt")

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response.text, "hola")

    def test_user_can_cancel_and_retry_job(self) -> None:
        self.app.dependency_overrides[get_authenticated_user_context] = self._juridica_user_context

        with TestClient(self.app) as client:
            resource_id = self._upload_media(client)
            deploy_response = client.post(
                "/api/jobs/deploy",
                json={"agent_id": "juridica", "resource_ids": [resource_id], "options": {}},
            )
            job_id = deploy_response.json()["job_id"]
            cancel_response = client.post(f"/api/jobs/{job_id}/cancel")
            retry_response = client.post(f"/api/jobs/{job_id}/retry")
            requeue_response = client.post(f"/api/jobs/{job_id}/requeue")

        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(cancel_response.json()["status"], "canceled")
        self.assertEqual(retry_response.status_code, 200)
        self.assertEqual(retry_response.json()["status"], "queued")
        self.assertEqual(requeue_response.status_code, 200)
        self.assertEqual(requeue_response.json()["status"], "queued")


if __name__ == "__main__":
    unittest.main()
