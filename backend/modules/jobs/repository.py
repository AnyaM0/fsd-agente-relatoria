from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from backend.core.config import Settings
from backend.infra.clients import AppClients
from backend.modules.jobs.models import JobRecord

try:
    from azure.cosmos import PartitionKey
except ImportError:  # pragma: no cover
    PartitionKey = None  # type: ignore[assignment]


class JobRepository(ABC):
    @abstractmethod
    async def create(self, record: JobRecord) -> JobRecord: ...

    @abstractmethod
    async def get(self, owner_object_id: str, job_id: str) -> JobRecord | None: ...

    @abstractmethod
    async def list_for_owner(self, owner_object_id: str) -> list[JobRecord]: ...

    @abstractmethod
    async def list_all(self) -> list[JobRecord]: ...

    @abstractmethod
    async def update(self, record: JobRecord) -> JobRecord: ...


class InMemoryJobRepository(JobRepository):
    def __init__(self) -> None:
        self._items: dict[str, JobRecord] = {}

    async def create(self, record: JobRecord) -> JobRecord:
        self._items[record.job_id] = record
        return record

    async def get(self, owner_object_id: str, job_id: str) -> JobRecord | None:
        item = self._items.get(job_id)
        if item is None or item.owner_object_id != owner_object_id:
            return None
        return item

    async def list_for_owner(self, owner_object_id: str) -> list[JobRecord]:
        items = [item for item in self._items.values() if item.owner_object_id == owner_object_id]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    async def list_all(self) -> list[JobRecord]:
        return sorted(self._items.values(), key=lambda item: item.created_at, reverse=True)

    async def update(self, record: JobRecord) -> JobRecord:
        self._items[record.job_id] = record
        return record


class CosmosJobRepository(JobRepository):
    def __init__(self, clients: AppClients, settings: Settings) -> None:
        if clients.cosmos_client is None:
            raise ValueError("Cosmos client is not configured.")
        self._cosmos_client = clients.cosmos_client
        self._database_name = settings.cosmos_database_name
        self._container_name = settings.cosmos_jobs_container_name
        self._auto_create = settings.cosmos_auto_create_containers

    async def create(self, record: JobRecord) -> JobRecord:
        container = await self._get_container()
        await container.upsert_item(self._to_document(record))
        return record

    async def get(self, owner_object_id: str, job_id: str) -> JobRecord | None:
        container = await self._get_container()
        try:
            item = await container.read_item(item=job_id, partition_key=owner_object_id)
        except Exception:
            return None
        return self._from_document(item)

    async def list_for_owner(self, owner_object_id: str) -> list[JobRecord]:
        container = await self._get_container()
        items = container.query_items(
            query="SELECT * FROM c WHERE c.owner_object_id = @owner",
            parameters=[{"name": "@owner", "value": owner_object_id}],
            partition_key=owner_object_id,
        )
        records = [self._from_document(item) async for item in items]
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    async def list_all(self) -> list[JobRecord]:
        container = await self._get_container()
        items = container.query_items(
            query="SELECT * FROM c",
            enable_cross_partition_query=True,
        )
        records = [self._from_document(item) async for item in items]
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    async def update(self, record: JobRecord) -> JobRecord:
        container = await self._get_container()
        await container.upsert_item(self._to_document(record))
        return record

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

    def _to_document(self, record: JobRecord) -> dict[str, Any]:
        return {"id": record.job_id, **record.model_dump()}

    def _from_document(self, item: dict[str, Any]) -> JobRecord:
        payload = {k: v for k, v in item.items() if k not in {"id", "_rid", "_self", "_etag", "_attachments", "_ts"}}
        return JobRecord.model_validate(payload)


def create_job_repository(settings: Settings, clients: AppClients) -> JobRepository:
    if settings.cosmos_enabled and clients.cosmos_client is not None:
        return CosmosJobRepository(clients, settings)
    return InMemoryJobRepository()
