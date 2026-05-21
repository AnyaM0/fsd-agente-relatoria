from __future__ import annotations

import unittest

from backend.core.config import Settings
from backend.modules.admin.models import UserAccount
from backend.modules.jobs.models import JobRecord
from backend.modules.notifications.service import NoopEmailNotificationBackend, NotificationService


class BackendNotificationsTests(unittest.TestCase):
    def test_html_notification_uses_branding_and_frontend_link(self) -> None:
        settings = Settings(
            BACKEND_FRONTEND_BASE_URL="https://fsddomiactaswebdev.z20.web.core.windows.net",
            BACKEND_NOTIFICATIONS_EMAIL_ENABLED=True,
        )
        service = NotificationService(settings, NoopEmailNotificationBackend())
        user = UserAccount(
            entra_object_id="oid-1",
            email="user@example.com",
            display_name="Daniel Sanchez",
            enabled=True,
            is_admin=True,
            allowed_agent_ids=["compras"],
        )
        job = JobRecord(
            job_id="job-123",
            owner_object_id="oid-1",
            agent_id="compras",
            job_tag="compras",
            resource_ids=["res-1"],
            status="completed",
            current_step="uploading_artifacts",
            progress=100,
            dispatch_backend="service_bus",
            worker_payload={},
        )

        html = service._build_html_body(user=user, job=job, link=service._build_frontend_job_link(job.job_id))

        self.assertIn("DOMI", html)
        self.assertIn("Actas", html)
        self.assertIn("LogoHorizontalFSD.svg", html)
        self.assertIn("Abrir en DOMI", html)
        self.assertIn("Acta de Compras", html)
        self.assertIn("job-123", html)


if __name__ == "__main__":
    unittest.main()
