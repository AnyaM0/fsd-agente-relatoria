from __future__ import annotations

import asyncio

from azure.cosmos import PartitionKey

from backend.core.config import get_settings
from backend.infra.clients import close_app_clients, create_app_clients


async def _bootstrap() -> int:
    settings = get_settings()
    if not settings.cosmos_enabled:
        raise RuntimeError("Cosmos is not configured.")

    clients = create_app_clients(settings)
    try:
        if clients.cosmos_client is None:
            raise RuntimeError("Cosmos client is not configured.")

        database = await clients.cosmos_client.create_database_if_not_exists(id=settings.cosmos_database_name)
        await database.create_container_if_not_exists(
            id=settings.cosmos_admin_container_name,
            partition_key=PartitionKey(path="/kind"),
        )
        await database.create_container_if_not_exists(
            id=settings.cosmos_resources_container_name,
            partition_key=PartitionKey(path="/owner_object_id"),
        )
        await database.create_container_if_not_exists(
            id=settings.cosmos_jobs_container_name,
            partition_key=PartitionKey(path="/owner_object_id"),
        )
        return 0
    finally:
        await close_app_clients(clients)


def main() -> int:
    return asyncio.run(_bootstrap())


if __name__ == "__main__":
    raise SystemExit(main())
