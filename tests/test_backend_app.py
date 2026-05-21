from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import get_settings
from backend.core.security import EntraPrincipal, get_token_validator


class BackendAppTests(unittest.TestCase):
    BASE_DISABLED_ENV = {
        "BACKEND_COSMOS_ACCOUNT_ENDPOINT": "",
        "BACKEND_BLOB_ACCOUNT_URL": "",
        "BACKEND_SERVICEBUS_FULLY_QUALIFIED_NAMESPACE": "",
        "BACKEND_ENTRA_ENABLED": "false",
        "BACKEND_ENTRA_TENANT_ID": "",
        "BACKEND_ENTRA_CLIENT_ID": "",
        "BACKEND_ENTRA_AUDIENCE": "",
    }

    def setUp(self) -> None:
        get_settings.cache_clear()
        get_token_validator.cache_clear()

    def tearDown(self) -> None:
        get_settings.cache_clear()
        get_token_validator.cache_clear()

    def test_health_endpoint_returns_backend_capabilities(self) -> None:
        with patch.dict(os.environ, self.BASE_DISABLED_ENV, clear=False):
            get_settings.cache_clear()
            get_token_validator.cache_clear()
            app = create_app()
            with TestClient(app) as client:
                response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["app"])
        self.assertFalse(payload["cosmos_enabled"])
        self.assertFalse(payload["blob_enabled"])
        self.assertFalse(payload["entra_enabled"])

    def test_auth_me_returns_503_when_entra_enabled_but_incomplete(self) -> None:
        with patch.dict(
            os.environ,
            {**self.BASE_DISABLED_ENV, "BACKEND_ENTRA_ENABLED": "true"},
            clear=False,
        ):
            get_settings.cache_clear()
            get_token_validator.cache_clear()
            app = create_app()
            with TestClient(app) as client:
                response = client.get("/api/auth/me")

        self.assertEqual(response.status_code, 503)

    def test_auth_me_requires_bearer_token_when_entra_is_enabled(self) -> None:
        with patch.dict(
            os.environ,
            {**self.BASE_DISABLED_ENV,
                "BACKEND_ENTRA_ENABLED": "true",
                "BACKEND_ENTRA_TENANT_ID": "tenant-id",
                "BACKEND_ENTRA_CLIENT_ID": "client-id",
                "BACKEND_ENTRA_AUDIENCE": "api://fsd-domiactas",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            get_token_validator.cache_clear()
            app = create_app()
            with TestClient(app) as client:
                response = client.get("/api/auth/me")

        self.assertEqual(response.status_code, 401)

    def test_auth_me_returns_principal_when_token_is_valid(self) -> None:
        principal = EntraPrincipal(
            token="token",
            claims={"sub": "user-123", "preferred_username": "user@example.com"},
            validation_mode="jwks",
        )

        with patch.dict(
            os.environ,
            {**self.BASE_DISABLED_ENV,
                "BACKEND_ENTRA_ENABLED": "true",
                "BACKEND_ENTRA_TENANT_ID": "tenant-id",
                "BACKEND_ENTRA_CLIENT_ID": "client-id",
                "BACKEND_ENTRA_AUDIENCE": "api://fsd-domiactas",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            get_token_validator.cache_clear()
            app = create_app()
            with patch("backend.core.security.get_token_validator") as validator_factory:
                validator_factory.return_value.validate_token.return_value = principal
                with TestClient(app) as client:
                    response = client.get("/api/auth/me", headers={"Authorization": "Bearer token"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["authenticated"])
        self.assertEqual(payload["principal"]["claims"]["sub"], "user-123")

    def test_new_entra_user_is_auto_provisioned_disabled(self) -> None:
        principal = EntraPrincipal(
            token="token",
            claims={
                "oid": "new-user-001",
                "preferred_username": "new.user@example.com",
                "name": "New User",
            },
            validation_mode="jwks",
        )

        with patch.dict(
            os.environ,
            {
                **self.BASE_DISABLED_ENV,
                "BACKEND_ENTRA_ENABLED": "true",
                "BACKEND_ENTRA_TENANT_ID": "tenant-id",
                "BACKEND_ENTRA_CLIENT_ID": "client-id",
                "BACKEND_ENTRA_AUDIENCE": "api://fsd-domiactas",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            get_token_validator.cache_clear()
            app = create_app()
            with patch("backend.core.security.get_token_validator") as validator_factory:
                validator_factory.return_value.validate_token.return_value = principal
                with TestClient(app) as client:
                    me_response = client.get("/api/auth/me", headers={"Authorization": "Bearer token"})
                    resources_response = client.get("/api/resources", headers={"Authorization": "Bearer token"})

            user = asyncio.run(app.state.admin_service.get_user("new-user-001"))

        self.assertEqual(me_response.status_code, 200)
        me_payload = me_response.json()
        self.assertEqual(me_payload["user"]["entra_object_id"], "new-user-001")
        self.assertFalse(me_payload["user"]["enabled"])
        self.assertEqual(me_payload["user"]["email"], "new.user@example.com")
        self.assertEqual(me_payload["user"]["display_name"], "New User")
        self.assertEqual(resources_response.status_code, 403)
        self.assertIsNotNone(user)
        self.assertFalse(user.enabled)
        self.assertEqual(user.allowed_agent_ids, [])


if __name__ == "__main__":
    unittest.main()
