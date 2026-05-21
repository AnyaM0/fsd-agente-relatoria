from __future__ import annotations

from agents.shared_tools.meeting_minutes.unified_pipeline import list_supported_meeting_domains
from backend.modules.admin.models import (
    AdminCapabilities,
    AgentCreateRequest,
    AgentDefinition,
    AgentUpdateRequest,
    UserAccount,
    UserUpsertRequest,
)
from backend.modules.admin.repository import AdminRepository


def get_builtin_agents() -> list[AgentDefinition]:
    return [
        AgentDefinition(
            agent_id="compras",
            display_name="Acta de Compras",
            description="Agente de compras para actas y memos de aprobacion.",
            job_tag="compras",
            pipeline_domain="compras",
            accepted_resource_kinds=["audio", "video", "ppt"],
            requires_primary_media=True,
            allows_context_ppt=True,
        ),
        AgentDefinition(
            agent_id="juridica",
            display_name="Acta Juridica",
            description="Agente juridico para actas, decisiones y recomendaciones.",
            job_tag="juridica",
            pipeline_domain="juridica",
            accepted_resource_kinds=["audio", "video", "ppt"],
            requires_primary_media=True,
            allows_context_ppt=True,
        ),
        AgentDefinition(
            agent_id="proyectos",
            display_name="Acta de Proyectos",
            description="Agente para actas de comités de proyectos: avances, riesgos, decisiones y compromisos.",
            job_tag="proyectos",
            pipeline_domain="proyectos",
            accepted_resource_kinds=["audio", "video", "ppt"],
            requires_primary_media=True,
            allows_context_ppt=True,
        ),
    ]


class AdminService:
    def __init__(self, repository: AdminRepository) -> None:
        self.repository = repository

    async def seed_builtin_agents(self) -> None:
        await self.repository.seed_builtin_agents(get_builtin_agents())

    async def get_capabilities(self) -> AdminCapabilities:
        return AdminCapabilities(
            runtime_domains=list(list_supported_meeting_domains()),
            registered_agents=await self.repository.list_agents(),
        )

    async def list_agents(self) -> list[AgentDefinition]:
        return await self.repository.list_agents()

    async def get_agent(self, agent_id: str) -> AgentDefinition | None:
        return await self.repository.get_agent(agent_id)

    async def create_agent(self, payload: AgentCreateRequest) -> AgentDefinition:
        return await self.repository.create_agent(payload)

    async def update_agent(self, agent_id: str, payload: AgentUpdateRequest) -> AgentDefinition | None:
        return await self.repository.update_agent(agent_id, payload)

    async def list_users(self) -> list[UserAccount]:
        return await self.repository.list_users()

    async def get_user(self, entra_object_id: str) -> UserAccount | None:
        return await self.repository.get_user(entra_object_id)

    async def ensure_user_exists(
        self,
        entra_object_id: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
    ) -> UserAccount:
        current = await self.repository.get_user(entra_object_id)
        if current is not None:
            return current
        return await self.repository.upsert_user(
            entra_object_id,
            UserUpsertRequest(
                email=email,
                display_name=display_name,
                enabled=False,
                is_admin=False,
                allowed_agent_ids=[],
                metadata={"auto_provisioned": True},
            ),
        )

    async def upsert_user(self, entra_object_id: str, payload: UserUpsertRequest) -> UserAccount:
        await self._validate_agent_ids(payload.allowed_agent_ids)
        return await self.repository.upsert_user(entra_object_id, payload)

    async def set_user_allowed_agents(self, entra_object_id: str, allowed_agent_ids: list[str]) -> UserAccount | None:
        await self._validate_agent_ids(allowed_agent_ids)
        return await self.repository.set_user_allowed_agents(entra_object_id, allowed_agent_ids)

    async def grant_agent_access(self, entra_object_id: str, agent_id: str) -> UserAccount | None:
        await self._validate_agent_ids([agent_id])
        user = await self.repository.get_user(entra_object_id)
        if user is None:
            return None
        return await self.repository.set_user_allowed_agents(
            entra_object_id,
            sorted(set(user.allowed_agent_ids + [agent_id])),
        )

    async def revoke_agent_access(self, entra_object_id: str, agent_id: str) -> UserAccount | None:
        user = await self.repository.get_user(entra_object_id)
        if user is None:
            return None
        return await self.repository.set_user_allowed_agents(
            entra_object_id,
            [item for item in user.allowed_agent_ids if item != agent_id],
        )

    async def _validate_agent_ids(self, agent_ids: list[str]) -> None:
        missing = []
        for agent_id in sorted(set(agent_ids)):
            if await self.repository.get_agent(agent_id) is None:
                missing.append(agent_id)
        if missing:
            raise ValueError(f"Unknown agent ids: {', '.join(missing)}.")
