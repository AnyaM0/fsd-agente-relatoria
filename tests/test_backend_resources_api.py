from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import get_settings
from backend.core.security import EntraPrincipal, get_token_validator
from backend.http.dependencies import AuthenticatedUserContext, get_authenticated_user_context
from backend.modules.admin.models import UserAccount


class BackendResourcesApiTests(unittest.TestCase):
    VALID_MP4_BYTES = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"

    def setUp(self) -> None:
        get_settings.cache_clear()
        get_token_validator.cache_clear()
        self.tempdir = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(
            os.environ,
            {
                "BACKEND_LOCAL_STORAGE_PATH": self.tempdir.name,
                "BACKEND_BLOB_ACCOUNT_URL": "",
                "BACKEND_COSMOS_ACCOUNT_ENDPOINT": "",
            },
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
    async def _allowed_user_context() -> AuthenticatedUserContext:
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
    async def _disallowed_user_context() -> AuthenticatedUserContext:
        return AuthenticatedUserContext(
            principal=EntraPrincipal(token="token", claims={"oid": "user-oid"}, validation_mode="test"),
            user=UserAccount(
                entra_object_id="user-oid",
                email="user@example.com",
                display_name="Test User",
                enabled=True,
                allowed_agent_ids=["compras"],
            ),
        )

    def test_user_can_upload_and_list_resources_for_allowed_agent(self) -> None:
        self.app.dependency_overrides[get_authenticated_user_context] = self._allowed_user_context

        with TestClient(self.app) as client:
            upload_response = client.post(
                "/api/resources/upload",
                data={"agent_id": "juridica"},
                files={"file": ("session.mp4", self.VALID_MP4_BYTES, "video/mp4")},
            )
            list_response = client.get("/api/resources")

        self.assertEqual(upload_response.status_code, 201)
        payload = upload_response.json()
        self.assertEqual(payload["agent_id"], "juridica")
        self.assertEqual(payload["resource_kind"], "video")
        self.assertEqual(payload["storage_backend"], "local")
        self.assertTrue(os.path.exists(payload["storage_path"]))

        self.assertEqual(list_response.status_code, 200)
        resources = list_response.json()
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["resource_id"], payload["resource_id"])
        self.assertEqual(resources[0]["usage_count"], 0)
        self.assertIsNone(resources[0]["latest_job"])
        self.assertEqual(resources[0]["related_jobs"], [])

    def test_user_can_fetch_resource_content(self) -> None:
        self.app.dependency_overrides[get_authenticated_user_context] = self._allowed_user_context

        with TestClient(self.app) as client:
            upload_response = client.post(
                "/api/resources/upload",
                data={"agent_id": "juridica"},
                files={"file": ("session.mp4", self.VALID_MP4_BYTES, "video/mp4")},
            )
            payload = upload_response.json()
            content_response = client.get(f"/api/resources/{payload['resource_id']}/content")

        self.assertEqual(upload_response.status_code, 201)
        self.assertEqual(content_response.status_code, 200)
        self.assertEqual(content_response.headers["content-type"], "video/mp4")
        self.assertIn("inline;", content_response.headers["content-disposition"])
        self.assertEqual(content_response.content, self.VALID_MP4_BYTES)

    def test_upload_is_rejected_when_agent_is_not_enabled_for_user(self) -> None:
        self.app.dependency_overrides[get_authenticated_user_context] = self._disallowed_user_context

        with TestClient(self.app) as client:
            response = client.post(
                "/api/resources/upload",
                data={"agent_id": "juridica"},
                files={"file": ("session.mp4", b"video-bytes", "video/mp4")},
            )

        self.assertEqual(response.status_code, 403)

    def test_upload_rejects_unsupported_resource_type(self) -> None:
        self.app.dependency_overrides[get_authenticated_user_context] = self._allowed_user_context

        with TestClient(self.app) as client:
            response = client.post(
                "/api/resources/upload",
                data={"agent_id": "juridica"},
                files={"file": ("notes.txt", b"text", "text/plain")},
            )

        self.assertEqual(response.status_code, 400)

    def test_upload_rejects_invalid_file_signature(self) -> None:
        self.app.dependency_overrides[get_authenticated_user_context] = self._allowed_user_context

        with TestClient(self.app) as client:
            response = client.post(
                "/api/resources/upload",
                data={"agent_id": "juridica"},
                files={"file": ("session.mp4", b"not-a-real-mp4", "video/mp4")},
            )

        self.assertEqual(response.status_code, 400)

    def test_upload_rejects_file_too_large(self) -> None:
        self.app.dependency_overrides[get_authenticated_user_context] = self._allowed_user_context

        with TestClient(self.app) as client:
            self.app.state.settings.resources_max_upload_size_bytes = 8
            response = client.post(
                "/api/resources/upload",
                data={"agent_id": "juridica"},
                files={"file": ("session.mp4", self.VALID_MP4_BYTES, "video/mp4")},
            )

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
