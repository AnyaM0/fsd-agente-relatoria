from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.azure.local", ".env.backend.local"),
        env_file_encoding="utf-8",
        env_prefix="BACKEND_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "fsd-domiactas-backend"
    app_version: str = "1.0.1"
    environment: str = "local"
    debug: bool = False
    api_prefix: str = "/api"
    cors_allowed_origins: list[str] = Field(default_factory=list)

    azure_use_default_credential: bool = True

    cosmos_account_endpoint: str | None = None
    cosmos_database_name: str = "fsd-domiactas"
    cosmos_jobs_container_name: str = "meeting-jobs"
    cosmos_artifacts_container_name: str = "meeting-artifacts"
    cosmos_admin_container_name: str = "admin-config"
    cosmos_resources_container_name: str = "resources"
    cosmos_auto_create_containers: bool = True

    blob_account_url: str | None = None
    blob_artifacts_container_name: str = "meeting-artifacts"
    blob_uploads_container_name: str = "meeting-uploads"
    local_storage_path: str = ".backend_storage"

    servicebus_fully_qualified_namespace: str | None = None
    servicebus_jobs_queue_name: str = "meeting-jobs"
    servicebus_job_retry_delay_seconds: int = 300
    azure_batch_max_wait_hours: float = 6.0
    jobs_max_attempts: int = 3
    jobs_stale_heartbeat_seconds: int = 1800

    resources_max_upload_size_bytes: int = 2 * 1024 * 1024 * 1024
    resources_enable_signature_validation: bool = True
    resources_enable_malware_scan: bool = False

    frontend_base_url: str | None = None
    frontend_job_url_template: str = "/jobs/{job_id}"

    notifications_email_enabled: bool = False
    notifications_email_backend: str = "noop"
    notifications_email_sender: str | None = None
    notifications_email_reply_to: str | None = None
    notifications_smtp_host: str | None = None
    notifications_smtp_port: int = 587
    notifications_smtp_username: str | None = None
    notifications_smtp_password: str | None = None
    notifications_smtp_use_tls: bool = True
    notifications_smtp_use_ssl: bool = False

    entra_enabled: bool = False
    entra_tenant_id: str | None = None
    entra_client_id: str | None = None
    entra_audience: str | None = None
    entra_authority_host: str = "https://login.microsoftonline.com"
    entra_metadata_url: str | None = None
    entra_expected_issuer: str | None = None
    entra_allowed_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    entra_clock_skew_seconds: int = 60
    entra_jwks_cache_ttl_seconds: int = 3600

    admin_bootstrap_object_ids: list[str] = Field(default_factory=list)
    admin_required_roles: list[str] = Field(default_factory=lambda: ["FSD.Admin"])
    admin_required_scopes: list[str] = Field(default_factory=list)

    @property
    def cosmos_enabled(self) -> bool:
        return bool(self.cosmos_account_endpoint)

    @property
    def blob_enabled(self) -> bool:
        return bool(self.blob_account_url)

    @property
    def servicebus_enabled(self) -> bool:
        return bool(self.servicebus_fully_qualified_namespace and self.servicebus_jobs_queue_name)

    @property
    def entra_configured(self) -> bool:
        return bool(self.entra_tenant_id and self.entra_client_id and self.entra_audience)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
