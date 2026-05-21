from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import unittest

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.security import EntraPrincipal, require_admin_principal
from backend.modules.jobs.models import JobRecord


class BackendAdminApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app()
        self.app.dependency_overrides[require_admin_principal] = self._override_admin

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()

    @staticmethod
    async def _override_admin() -> EntraPrincipal:
        return EntraPrincipal(
            token="token",
            claims={"oid": "admin-oid", "roles": ["FSD.Admin"]},
            validation_mode="test",
        )

    def test_admin_capabilities_and_builtin_agents(self) -> None:
        with TestClient(self.app) as client:
            response = client.get("/api/admin/capabilities")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["runtime_domains"], ["compras", "juridica"])
        agent_ids = [item["agent_id"] for item in payload["registered_agents"]]
        self.assertEqual(agent_ids, ["compras", "juridica"])

    def test_admin_can_create_and_update_agent(self) -> None:
        with TestClient(self.app) as client:
            create_response = client.post(
                "/api/admin/agents",
                json={
                    "agent_id": "riesgos",
                    "display_name": "Acta de Riesgos",
                    "description": "Agente para riesgos.",
                    "job_tag": "riesgos",
                    "pipeline_domain": "juridica",
                },
            )
            update_response = client.put(
                "/api/admin/agents/riesgos",
                json={
                    "enabled": False,
                    "description": "Agente temporalmente pausado.",
                },
            )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(update_response.status_code, 200)
        payload = update_response.json()
        self.assertFalse(payload["enabled"])
        self.assertEqual(payload["job_tag"], "riesgos")

    def test_admin_can_manage_users_and_agent_access(self) -> None:
        with TestClient(self.app) as client:
            create_user = client.put(
                "/api/admin/users/user-001",
                json={
                    "email": "user@example.com",
                    "display_name": "Test User",
                    "enabled": True,
                    "is_admin": False,
                    "allowed_agent_ids": ["juridica"],
                },
            )
            grant = client.post("/api/admin/users/user-001/agents/compras")
            revoke = client.delete("/api/admin/users/user-001/agents/juridica")
            get_user = client.get("/api/admin/users/user-001")

        self.assertEqual(create_user.status_code, 200)
        self.assertEqual(grant.status_code, 200)
        self.assertEqual(revoke.status_code, 200)
        payload = get_user.json()
        self.assertEqual(payload["allowed_agent_ids"], ["compras"])

    def test_admin_rejects_unknown_agent_assignment(self) -> None:
        with TestClient(self.app) as client:
            client.put(
                "/api/admin/users/user-002",
                json={
                    "email": "user2@example.com",
                    "display_name": "Test User 2",
                    "enabled": True,
                    "is_admin": False,
                    "allowed_agent_ids": [],
                },
            )
            response = client.put(
                "/api/admin/users/user-002/agents",
                json={"allowed_agent_ids": ["desconocido"]},
            )

        self.assertEqual(response.status_code, 400)

    def test_admin_can_list_and_rescue_stale_user_jobs(self) -> None:
        stale_heartbeat = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        with TestClient(self.app) as client:
            client.put(
                "/api/admin/users/user-003",
                json={
                    "email": "user3@example.com",
                    "display_name": "Test User 3",
                    "enabled": True,
                    "is_admin": False,
                    "allowed_agent_ids": ["juridica"],
                },
            )

            record = JobRecord(
                job_id="job-003",
                owner_object_id="user-003",
                agent_id="juridica",
                job_tag="juridica",
                resource_ids=["resource-1"],
                status="preparing_audio",
                current_step="preparing_audio",
                progress=30,
                dispatch_backend="noop",
                worker_payload={
                    "job_id": "job-003",
                    "owner_object_id": "user-003",
                    "agent_id": "juridica",
                    "job_tag": "juridica",
                    "resource_ids": ["resource-1"],
                    "resources": [],
                    "options": {},
                },
                created_at=stale_heartbeat,
                updated_at=stale_heartbeat,
                last_heartbeat_at=stale_heartbeat,
            )
            asyncio.run(self.app.state.job_repository.create(record))

            list_response = client.get("/api/admin/users/user-003/jobs")
            rescue_response = client.post("/api/admin/users/user-003/jobs/job-003/rescue")

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)
        self.assertEqual(rescue_response.status_code, 200)
        self.assertEqual(rescue_response.json()["status"], "queued")

    def test_admin_can_retry_failed_user_jobs(self) -> None:
        failed_at = datetime.now(timezone.utc).isoformat()

        with TestClient(self.app) as client:
            client.put(
                "/api/admin/users/user-004",
                json={
                    "email": "user4@example.com",
                    "display_name": "Test User 4",
                    "enabled": True,
                    "is_admin": False,
                    "allowed_agent_ids": ["compras"],
                },
            )

            record = JobRecord(
                job_id="job-004",
                owner_object_id="user-004",
                agent_id="compras",
                job_tag="compras",
                resource_ids=["resource-2"],
                status="dead_lettered",
                current_step="dead_lettered",
                progress=100,
                dispatch_backend="noop",
                worker_payload={
                    "job_id": "job-004",
                    "owner_object_id": "user-004",
                    "agent_id": "compras",
                    "job_tag": "compras",
                    "resource_ids": ["resource-2"],
                    "resources": [],
                    "options": {},
                },
                created_at=failed_at,
                updated_at=failed_at,
                completed_at=failed_at,
                error={"type": "RuntimeError", "message": "failure"},
            )
            asyncio.run(self.app.state.job_repository.create(record))

            retry_response = client.post("/api/admin/users/user-004/jobs/job-004/retry")

        self.assertEqual(retry_response.status_code, 200)
        self.assertEqual(retry_response.json()["status"], "queued")


if __name__ == "__main__":
    unittest.main()
