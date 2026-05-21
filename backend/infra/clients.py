from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from azure.identity.aio import DefaultAzureCredential

from backend.core.config import Settings

try:
    from azure.cosmos.aio import CosmosClient
except ImportError:  # pragma: no cover
    CosmosClient = Any  # type: ignore[assignment]

try:
    from azure.storage.blob.aio import BlobServiceClient
except ImportError:  # pragma: no cover
    BlobServiceClient = Any  # type: ignore[assignment]

try:
    from azure.servicebus.aio import ServiceBusClient
except ImportError:  # pragma: no cover
    ServiceBusClient = Any  # type: ignore[assignment]


@dataclass
class AppClients:
    credential: DefaultAzureCredential | None
    cosmos_client: CosmosClient | None
    blob_service_client: BlobServiceClient | None
    servicebus_client: ServiceBusClient | None


def create_app_clients(settings: Settings) -> AppClients:
    credential = None
    cosmos_client = None
    blob_service_client = None
    servicebus_client = None

    if settings.azure_use_default_credential and (
        settings.cosmos_enabled or settings.blob_enabled or settings.servicebus_enabled
    ):
        credential = DefaultAzureCredential()

    if settings.cosmos_enabled:
        cosmos_client = CosmosClient(settings.cosmos_account_endpoint, credential=credential)

    if settings.blob_enabled:
        blob_service_client = BlobServiceClient(account_url=settings.blob_account_url, credential=credential)

    if settings.servicebus_enabled:
        servicebus_client = ServiceBusClient(
            fully_qualified_namespace=settings.servicebus_fully_qualified_namespace,
            credential=credential,
        )

    return AppClients(
        credential=credential,
        cosmos_client=cosmos_client,
        blob_service_client=blob_service_client,
        servicebus_client=servicebus_client,
    )


async def close_app_clients(clients: AppClients) -> None:
    if clients.cosmos_client is not None:
        await clients.cosmos_client.close()
    if clients.blob_service_client is not None:
        await clients.blob_service_client.close()
    if clients.servicebus_client is not None:
        await clients.servicebus_client.close()
    if clients.credential is not None:
        await clients.credential.close()
