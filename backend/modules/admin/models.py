from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentDefinition(BaseModel):
    agent_id: str
    display_name: str
    description: str = ""
    job_tag: str
    pipeline_domain: str | None = None
    enabled: bool = True
    supports_audio: bool = True
    supports_ppt: bool = True
    accepted_resource_kinds: list[Literal["audio", "video", "ppt"]] = Field(
        default_factory=lambda: ["audio", "video", "ppt"]
    )
    requires_primary_media: bool = True
    allows_context_ppt: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class AgentCreateRequest(BaseModel):
    agent_id: str
    display_name: str
    description: str = ""
    job_tag: str
    pipeline_domain: str | None = None
    enabled: bool = True
    supports_audio: bool = True
    supports_ppt: bool = True
    accepted_resource_kinds: list[Literal["audio", "video", "ppt"]] = Field(
        default_factory=lambda: ["audio", "video", "ppt"]
    )
    requires_primary_media: bool = True
    allows_context_ppt: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentUpdateRequest(BaseModel):
    display_name: str | None = None
    description: str | None = None
    job_tag: str | None = None
    pipeline_domain: str | None = None
    enabled: bool | None = None
    supports_audio: bool | None = None
    supports_ppt: bool | None = None
    accepted_resource_kinds: list[Literal["audio", "video", "ppt"]] | None = None
    requires_primary_media: bool | None = None
    allows_context_ppt: bool | None = None
    metadata: dict[str, Any] | None = None


class UserAccount(BaseModel):
    entra_object_id: str
    email: str | None = None
    display_name: str | None = None
    enabled: bool = True
    is_admin: bool = False
    allowed_agent_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class UserUpsertRequest(BaseModel):
    email: str | None = None
    display_name: str | None = None
    enabled: bool = True
    is_admin: bool = False
    allowed_agent_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserAgentAccessUpdateRequest(BaseModel):
    allowed_agent_ids: list[str] = Field(default_factory=list)


class AdminCapabilities(BaseModel):
    runtime_domains: list[str]
    registered_agents: list[AgentDefinition]
