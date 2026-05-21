from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from backend.core.config import Settings
from backend.infra.clients import AppClients
from backend.modules.admin.models import (
    AgentCreateRequest,
    AgentDefinition,
    AgentUpdateRequest,
    UserAccount,
    UserUpsertRequest,
    utc_now_iso,
)

try:
    from azure.cosmos import PartitionKey
except ImportError:  # pragma: no cover
    PartitionKey = None  # type: ignore[assignment]


class AdminRepository(ABC):
    @abstractmethod
    async def seed_builtin_agents(self, agents: list[AgentDefinition]) -> None: ...

    @abstractmethod
    async def list_agents(self) -> list[AgentDefinition]: ...

    @abstractmethod
    async def get_agent(self, agent_id: str) -> AgentDefinition | None: ...

    @abstractmethod
    async def create_agent(self, payload: AgentCreateRequest) -> AgentDefinition: ...

    @abstractmethod
    async def update_agent(self, agent_id: str, payload: AgentUpdateRequest) -> AgentDefinition | None: ...

    @abstractmethod
    async def list_users(self) -> list[UserAccount]: ...

    @abstractmethod
    async def get_user(self, entra_object_id: str) -> UserAccount | None: ...

    @abstractmethod
    async def upsert_user(self, entra_object_id: str, payload: UserUpsertRequest) -> UserAccount: ...

    @abstractmethod
    async def set_user_allowed_agents(self, entra_object_id: str, allowed_agent_ids: list[str]) -> UserAccount | None: ...


class InMemoryAdminRepository(AdminRepository):
    def __init__(self) -> None:
        self._agents: dict[str, AgentDefinition] = {}
        self._users: dict[str, UserAccount] = {}

    async def seed_builtin_agents(self, agents: list[AgentDefinition]) -> None:
        for agent in agents:
            if agent.agent_id not in self._agents:
                self._agents[agent.agent_id] = agent

    async def list_agents(self) -> list[AgentDefinition]:
        return sorted(self._agents.values(), key=lambda item: item.agent_id)

    async def get_agent(self, agent_id: str) -> AgentDefinition | None:
        return self._agents.get(agent_id)

    async def create_agent(self, payload: AgentCreateRequest) -> AgentDefinition:
        now = utc_now_iso()
        agent = AgentDefinition(**payload.model_dump(), created_at=now, updated_at=now)
        self._agents[agent.agent_id] = agent
        return agent

    async def update_agent(self, agent_id: str, payload: AgentUpdateRequest) -> AgentDefinition | None:
        current = self._agents.get(agent_id)
        if current is None:
            return None
        updated = current.model_copy(update={**payload.model_dump(exclude_unset=True), "updated_at": utc_now_iso()})
        self._agents[agent_id] = updated
        return updated

    async def list_users(self) -> list[UserAccount]:
        return sorted(self._users.values(), key=lambda item: item.entra_object_id)

    async def get_user(self, entra_object_id: str) -> UserAccount | None:
        return self._users.get(entra_object_id)

    async def upsert_user(self, entra_object_id: str, payload: UserUpsertRequest) -> UserAccount:
        current = self._users.get(entra_object_id)
        if current is None:
            now = utc_now_iso()
            user = UserAccount(entra_object_id=entra_object_id, **payload.model_dump(), created_at=now, updated_at=now)
        else:
            user = current.model_copy(update={**payload.model_dump(), "updated_at": utc_now_iso()})
        self._users[entra_object_id] = user
        return user

    async def set_user_allowed_agents(self, entra_object_id: str, allowed_agent_ids: list[str]) -> UserAccount | None:
        current = self._users.get(entra_object_id)
        if current is None:
            return None
        updated = current.model_copy(
            update={"allowed_agent_ids": sorted(set(allowed_agent_ids)), "updated_at": utc_now_iso()}
        )
        self._users[entra_object_id] = updated
        return updated


class CosmosAdminRepository(AdminRepository):
    def __init__(self, clients: AppClients, settings: Settings) -> None:
        if clients.cosmos_client is None:
            raise ValueError("Cosmos client is not configured.")
        self._cosmos_client = clients.cosmos_client
        self._database_name = settings.cosmos_database_name
        self._container_name = settings.cosmos_admin_container_name
        self._auto_create = settings.cosmos_auto_create_containers

    async def seed_builtin_agents(self, agents: list[AgentDefinition]) -> None:
        container = await self._get_container()
        for agent in agents:
            existing = await self.get_agent(agent.agent_id)
            if existing is None:
                await container.upsert_item(self._agent_to_document(agent))

    async def list_agents(self) -> list[AgentDefinition]:
        container = await self._get_container()
        items = container.query_items(
            query="SELECT * FROM c WHERE c.kind = @kind",
            parameters=[{"name": "@kind", "value": "agent"}],
        )
        return [self._document_to_agent(item) async for item in items]

    async def get_agent(self, agent_id: str) -> AgentDefinition | None:
        container = await self._get_container()
        try:
            item = await container.read_item(item=self._agent_document_id(agent_id), partition_key="agent")
        except Exception:
            return None
        return self._document_to_agent(item)

    async def create_agent(self, payload: AgentCreateRequest) -> AgentDefinition:
        container = await self._get_container()
        now = utc_now_iso()
        agent = AgentDefinition(**payload.model_dump(), created_at=now, updated_at=now)
        await container.upsert_item(self._agent_to_document(agent))
        return agent

    async def update_agent(self, agent_id: str, payload: AgentUpdateRequest) -> AgentDefinition | None:
        current = await self.get_agent(agent_id)
        if current is None:
            return None
        updated = current.model_copy(update={**payload.model_dump(exclude_unset=True), "updated_at": utc_now_iso()})
        container = await self._get_container()
        await container.upsert_item(self._agent_to_document(updated))
        return updated

    async def list_users(self) -> list[UserAccount]:
        container = await self._get_container()
        items = container.query_items(
            query="SELECT * FROM c WHERE c.kind = @kind",
            parameters=[{"name": "@kind", "value": "user"}],
        )
        return [self._document_to_user(item) async for item in items]

    async def get_user(self, entra_object_id: str) -> UserAccount | None:
        container = await self._get_container()
        try:
            item = await container.read_item(item=self._user_document_id(entra_object_id), partition_key="user")
        except Exception:
            return None
        return self._document_to_user(item)

    async def upsert_user(self, entra_object_id: str, payload: UserUpsertRequest) -> UserAccount:
        current = await self.get_user(entra_object_id)
        if current is None:
            now = utc_now_iso()
            user = UserAccount(entra_object_id=entra_object_id, **payload.model_dump(), created_at=now, updated_at=now)
        else:
            user = current.model_copy(update={**payload.model_dump(), "updated_at": utc_now_iso()})
        container = await self._get_container()
        await container.upsert_item(self._user_to_document(user))
        return user

    async def set_user_allowed_agents(self, entra_object_id: str, allowed_agent_ids: list[str]) -> UserAccount | None:
        current = await self.get_user(entra_object_id)
        if current is None:
            return None
        updated = current.model_copy(
            update={"allowed_agent_ids": sorted(set(allowed_agent_ids)), "updated_at": utc_now_iso()}
        )
        container = await self._get_container()
        await container.upsert_item(self._user_to_document(updated))
        return updated

    async def _get_container(self):
        if PartitionKey is None:
            raise RuntimeError("azure-cosmos is not installed.")
        if self._auto_create:
            database = await self._cosmos_client.create_database_if_not_exists(id=self._database_name)
            return await database.create_container_if_not_exists(
                id=self._container_name,
                partition_key=PartitionKey(path="/kind"),
            )
        database = self._cosmos_client.get_database_client(self._database_name)
        return database.get_container_client(self._container_name)

    def _agent_document_id(self, agent_id: str) -> str:
        return f"agent:{agent_id}"

    def _user_document_id(self, entra_object_id: str) -> str:
        return f"user:{entra_object_id}"

    def _agent_to_document(self, agent: AgentDefinition) -> dict[str, Any]:
        return {"id": self._agent_document_id(agent.agent_id), "kind": "agent", **agent.model_dump()}

    def _user_to_document(self, user: UserAccount) -> dict[str, Any]:
        return {"id": self._user_document_id(user.entra_object_id), "kind": "user", **user.model_dump()}

    def _document_to_agent(self, item: dict[str, Any]) -> AgentDefinition:
        payload = {k: v for k, v in item.items() if k not in {"id", "kind", "_rid", "_self", "_etag", "_attachments", "_ts"}}
        return AgentDefinition.model_validate(payload)

    def _document_to_user(self, item: dict[str, Any]) -> UserAccount:
        payload = {k: v for k, v in item.items() if k not in {"id", "kind", "_rid", "_self", "_etag", "_attachments", "_ts"}}
        return UserAccount.model_validate(payload)


def create_admin_repository(settings: Settings, clients: AppClients) -> AdminRepository:
    if settings.cosmos_enabled and clients.cosmos_client is not None:
        return CosmosAdminRepository(clients, settings)
    return InMemoryAdminRepository()
