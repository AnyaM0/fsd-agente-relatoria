from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from backend.core.config import Settings
from backend.infra.clients import AppClients
from backend.modules.resources.models import ResourceRecord, UploadStatus

try:
    from azure.cosmos import PartitionKey
except ImportError:  # pragma: no cover
    PartitionKey = None  # type: ignore[assignment]


class ResourceRepository(ABC):
    @abstractmethod
    async def create(self, record: ResourceRecord) -> ResourceRecord: ...

    @abstractmethod
    async def get(self, owner_object_id: str, resource_id: str) -> ResourceRecord | None: ...

    @abstractmethod
    async def list_for_owner(
        self,
        owner_object_id: str,
        agent_id: str | None = None,
        upload_status: UploadStatus | None = "ready",
    ) -> list[ResourceRecord]: ...

    @abstractmethod
    async def update_upload_status(
        self, owner_object_id: str, resource_id: str, status: UploadStatus, size_bytes: int | None = None
    ) -> ResourceRecord | None: ...

    @abstractmethod
    async def delete(self, owner_object_id: str, resource_id: str) -> None: ...


class InMemoryResourceRepository(ResourceRepository):
    def __init__(self) -> None:
        self._items: dict[str, ResourceRecord] = {}

    async def create(self, record: ResourceRecord) -> ResourceRecord:
        self._items[record.resource_id] = record
        return record

    async def get(self, owner_object_id: str, resource_id: str) -> ResourceRecord | None:
        record = self._items.get(resource_id)
        if record is None or record.owner_object_id != owner_object_id:
            return None
        return record

    async def list_for_owner(
        self,
        owner_object_id: str,
        agent_id: str | None = None,
        upload_status: UploadStatus | None = "ready",
    ) -> list[ResourceRecord]:
        items = [item for item in self._items.values() if item.owner_object_id == owner_object_id]
        if agent_id is not None:
            items = [item for item in items if item.agent_id == agent_id]
        if upload_status is not None:
            items = [item for item in items if item.upload_status == upload_status]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    async def update_upload_status(
        self, owner_object_id: str, resource_id: str, status: UploadStatus, size_bytes: int | None = None
    ) -> ResourceRecord | None:
        record = self._items.get(resource_id)
        if record is None or record.owner_object_id != owner_object_id:
            return None
        updated = record.model_copy(update={"upload_status": status, **({"size_bytes": size_bytes} if size_bytes is not None else {})})
        self._items[resource_id] = updated
        return updated

    async def delete(self, owner_object_id: str, resource_id: str) -> None:
        record = self._items.get(resource_id)
        if record is not None and record.owner_object_id == owner_object_id:
            del self._items[resource_id]


class CosmosResourceRepository(ResourceRepository):
    def __init__(self, clients: AppClients, settings: Settings) -> None:
        if clients.cosmos_client is None:
            raise ValueError("Cosmos client is not configured.")
        self._cosmos_client = clients.cosmos_client
        self._database_name = settings.cosmos_database_name
        self._container_name = settings.cosmos_resources_container_name
        self._auto_create = settings.cosmos_auto_create_containers

    async def create(self, record: ResourceRecord) -> ResourceRecord:
        container = await self._get_container()
        await container.upsert_item(self._to_document(record))
        return record

    async def get(self, owner_object_id: str, resource_id: str) -> ResourceRecord | None:
        container = await self._get_container()
        try:
            item = await container.read_item(item=resource_id, partition_key=owner_object_id)
        except Exception:
            return None
        return self._from_document(item)

    async def list_for_owner(
        self,
        owner_object_id: str,
        agent_id: str | None = None,
        upload_status: UploadStatus | None = "ready",
    ) -> list[ResourceRecord]:
        container = await self._get_container()
        query = "SELECT * FROM c WHERE c.owner_object_id = @owner"
        parameters: list[dict[str, Any]] = [{"name": "@owner", "value": owner_object_id}]
        if agent_id is not None:
            query += " AND c.agent_id = @agent_id"
            parameters.append({"name": "@agent_id", "value": agent_id})
        if upload_status is not None:
            query += " AND (NOT IS_DEFINED(c.upload_status) OR c.upload_status = @upload_status)"
            parameters.append({"name": "@upload_status", "value": upload_status})
        items = container.query_items(query=query, parameters=parameters, partition_key=owner_object_id)
        return [self._from_document(item) async for item in items]

    async def update_upload_status(
        self, owner_object_id: str, resource_id: str, status: UploadStatus, size_bytes: int | None = None
    ) -> ResourceRecord | None:
        container = await self._get_container()
        try:
            item = await container.read_item(item=resource_id, partition_key=owner_object_id)
        except Exception:
            return None
        item["upload_status"] = status
        if size_bytes is not None:
            item["size_bytes"] = size_bytes
        await container.upsert_item(item)
        return self._from_document(item)

    async def delete(self, owner_object_id: str, resource_id: str) -> None:
        container = await self._get_container()
        try:
            await container.delete_item(item=resource_id, partition_key=owner_object_id)
        except Exception:
            pass

    async def _get_container(self):
        if PartitionKey is None:
            raise RuntimeError("azure-cosmos is not installed.")
        if self._auto_create:
            database = await self._cosmos_client.create_database_if_not_exists(id=self._database_name)
            return await database.create_container_if_not_exists(
                id=self._container_name,
                partition_key=PartitionKey(path="/owner_object_id"),
            )
        database = self._cosmos_client.get_database_client(self._database_name)
        return database.get_container_client(self._container_name)

    def _to_document(self, record: ResourceRecord) -> dict[str, Any]:
        return {"id": record.resource_id, **record.model_dump()}

    def _from_document(self, item: dict[str, Any]) -> ResourceRecord:
        payload = {k: v for k, v in item.items() if k not in {"id", "_rid", "_self", "_etag", "_attachments", "_ts"}}
        return ResourceRecord.model_validate(payload)


def create_resource_repository(settings: Settings, clients: AppClients) -> ResourceRepository:
    if settings.cosmos_enabled and clients.cosmos_client is not None:
        return CosmosResourceRepository(clients, settings)
    return InMemoryResourceRepository()
