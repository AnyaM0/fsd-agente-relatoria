from __future__ import annotations

import argparse
import asyncio
import json

from backend.core.config import get_settings
from backend.infra.clients import close_app_clients, create_app_clients
from backend.modules.admin.repository import create_admin_repository
from backend.modules.admin.service import AdminService
from backend.modules.jobs.dispatcher import create_job_dispatcher
from backend.modules.jobs.repository import create_job_repository
from backend.modules.jobs.worker import MeetingJobWorker
from backend.modules.notifications import create_notification_service
from backend.modules.resources.repository import create_resource_repository
from backend.modules.resources.service import ResourceService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the background worker for meeting jobs.")
    parser.add_argument("--once", action="store_true", help="Process a single message and exit.")
    return parser


async def _consume_messages(*, once: bool) -> int:
    settings = get_settings()
    clients = create_app_clients(settings)
    admin_repository = create_admin_repository(settings, clients)
    admin_service = AdminService(admin_repository)
    await admin_service.seed_builtin_agents()
    resource_repository = create_resource_repository(settings, clients)
    resource_service = ResourceService(resource_repository, admin_service, clients, settings)
    notification_service = create_notification_service(settings)
    job_repository = create_job_repository(settings, clients)
    job_dispatcher = create_job_dispatcher(settings, clients)
    worker = MeetingJobWorker(
        settings=settings,
        clients=clients,
        job_repository=job_repository,
        resource_service=resource_service,
        admin_service=admin_service,
        job_dispatcher=job_dispatcher,
        notification_service=notification_service,
    )

    try:
        if clients.servicebus_client is None or not settings.servicebus_enabled:
            raise RuntimeError("Service Bus is not configured for the worker.")

        async with clients.servicebus_client.get_queue_receiver(queue_name=settings.servicebus_jobs_queue_name) as receiver:
            while True:
                messages = await receiver.receive_messages(max_wait_time=10, max_message_count=1)
                if not messages:
                    if once:
                        return 0
                    continue

                for message in messages:
                    try:
                        body = b"".join(bytes(item) if not isinstance(item, bytes) else item for item in message.body)
                        payload = json.loads(body.decode("utf-8"))
                        await worker.process_payload(payload)
                        await receiver.complete_message(message)
                    except Exception:
                        await receiver.abandon_message(message)
                        raise

                if once:
                    return 0
    finally:
        await close_app_clients(clients)


def main() -> int:
    args = build_parser().parse_args()
    return asyncio.run(_consume_messages(once=args.once))


if __name__ == "__main__":
    raise SystemExit(main())
