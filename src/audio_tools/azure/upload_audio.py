from __future__ import annotations

import mimetypes
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from azure.core.credentials import AzureSasCredential, TokenCredential
from azure.identity import DefaultAzureCredential


@dataclass(frozen=True)
class UploadedAudioBlob:
    local_path: Path
    blob_name: str
    blob_url: str
    sas_url: str
    expires_at: datetime


class AzureBlobAudioStorage:
    def __init__(
        self,
        *,
        account_url: str,
        container_name: str,
        credential: TokenCredential | AzureNamedKeyCredential | AzureSasCredential | None = None,
        prefix: str = "audio",
        auto_create_container: bool = True,
    ) -> None:
        self.account_url = account_url.rstrip("/")
        self.container_name = container_name
        self.credential = credential or DefaultAzureCredential(exclude_interactive_browser_credential=True)
        self.prefix = prefix.strip("/")
        self.auto_create_container = auto_create_container
        self._service_client = None

    @classmethod
    def from_env(
        cls,
        *,
        prefix: str = "audio",
        auto_create_container: bool = True,
    ) -> "AzureBlobAudioStorage":
        account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL")
        container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME")

        if not container_name:
            raise ValueError("AZURE_STORAGE_CONTAINER_NAME is required.")
        if not account_url:
            raise ValueError("AZURE_STORAGE_ACCOUNT_URL is required.")

        return cls(
            account_url=account_url,
            container_name=container_name,
            credential=DefaultAzureCredential(),
            prefix=prefix,
            auto_create_container=auto_create_container,
        )

    def _blob_sdk(self) -> dict[str, Any]:
        try:
            from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
            from azure.storage.blob import (
                BlobSasPermissions,
                BlobServiceClient,
                ContentSettings,
                generate_blob_sas,
            )
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "azure-storage-blob is not installed. Add it to the environment before using AzureBlobAudioStorage."
            ) from exc

        return {
            "BlobSasPermissions": BlobSasPermissions,
            "BlobServiceClient": BlobServiceClient,
            "ContentSettings": ContentSettings,
            "ResourceExistsError": ResourceExistsError,
            "ResourceNotFoundError": ResourceNotFoundError,
            "generate_blob_sas": generate_blob_sas,
        }

    def _service(self):
        if self._service_client is None:
            sdk = self._blob_sdk()
            self._service_client = sdk["BlobServiceClient"](
                account_url=self.account_url,
                credential=self.credential,
            )
        return self._service_client

    def _container_client(self):
        return self._service().get_container_client(self.container_name)

    def ensure_container(self) -> None:
        if not self.auto_create_container:
            return

        sdk = self._blob_sdk()
        container = self._container_client()
        try:
            container.create_container()
        except sdk["ResourceExistsError"]:
            return

    def build_blob_name(self, file_path: str | Path, *, blob_name: str | None = None) -> str:
        if blob_name:
            return blob_name.lstrip("/")

        path = Path(file_path)
        suffix = path.suffix.lower()
        generated = f"{uuid.uuid4().hex}{suffix}"
        if self.prefix:
            return f"{self.prefix}/{generated}"
        return generated

    def upload_audio_file(
        self,
        file_path: str | Path,
        *,
        blob_name: str | None = None,
        overwrite: bool = False,
        metadata: dict[str, str] | None = None,
        sas_expiry_seconds: int = 3600,
    ) -> UploadedAudioBlob:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Audio file does not exist: {path}")
        if not path.is_file():
            raise ValueError(f"Audio path must be a file: {path}")

        with path.open("rb") as data:
            return self._upload_audio_data(
                data.read(),
                filename=path.name,
                source_path=path,
                blob_name=blob_name,
                overwrite=overwrite,
                metadata=metadata,
                sas_expiry_seconds=sas_expiry_seconds,
            )

    def upload_audio_bytes(
        self,
        data: bytes,
        *,
        filename: str = "audio.wav",
        blob_name: str | None = None,
        overwrite: bool = False,
        metadata: dict[str, str] | None = None,
        sas_expiry_seconds: int = 3600,
    ) -> UploadedAudioBlob:
        if not data:
            raise ValueError("Audio bytes cannot be empty.")

        return self._upload_audio_data(
            data,
            filename=filename,
            source_path=None,
            blob_name=blob_name,
            overwrite=overwrite,
            metadata=metadata,
            sas_expiry_seconds=sas_expiry_seconds,
        )

    def _upload_audio_data(
        self,
        data: bytes,
        *,
        filename: str,
        source_path: Path | None,
        blob_name: str | None,
        overwrite: bool,
        metadata: dict[str, str] | None,
        sas_expiry_seconds: int,
    ) -> UploadedAudioBlob:
        self.ensure_container()

        sdk = self._blob_sdk()
        blob_name = self.build_blob_name(filename, blob_name=blob_name)
        blob_client = self._container_client().get_blob_client(blob_name)

        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        content_settings = sdk["ContentSettings"](content_type=content_type)

        blob_client.upload_blob(
            data,
            overwrite=overwrite,
            metadata=metadata or {},
            content_settings=content_settings,
        )

        sas_url, expires_at = self.generate_read_sas_url(
            blob_name,
            expiry_seconds=sas_expiry_seconds,
        )

        return UploadedAudioBlob(
            local_path=source_path or Path(filename),
            blob_name=blob_name,
            blob_url=blob_client.url,
            sas_url=sas_url,
            expires_at=expires_at,
        )

    def generate_read_sas_url(
        self,
        blob_name: str,
        *,
        expiry_seconds: int = 3600,
        start_skew_minutes: int = 5,
    ) -> tuple[str, datetime]:
        sdk = self._blob_sdk()
        service = self._service()
        now = datetime.now(UTC)
        start = now - timedelta(minutes=start_skew_minutes)
        expiry = now + timedelta(seconds=expiry_seconds)

        sas_kwargs: dict[str, Any] = {
            "account_name": service.account_name,
            "container_name": self.container_name,
            "blob_name": blob_name,
            "permission": sdk["BlobSasPermissions"](read=True),
            "expiry": expiry,
            "start": start,
        }

        if isinstance(self.credential, TokenCredential):
            sas_kwargs["user_delegation_key"] = service.get_user_delegation_key(
                key_start_time=start,
                key_expiry_time=expiry,
            )
        else:
            raise ValueError(
                "AzureSasCredential cannot mint a new read SAS URL. Use DefaultAzureCredential instead."
            )

        sas_token = sdk["generate_blob_sas"](**sas_kwargs)

        blob_url = self._container_client().get_blob_client(blob_name).url
        return f"{blob_url}?{sas_token}", expiry

    def delete_blob(self, blob_name: str, *, missing_ok: bool = True) -> None:
        sdk = self._blob_sdk()
        blob_client = self._container_client().get_blob_client(blob_name)

        try:
            blob_client.delete_blob(delete_snapshots="include")
        except sdk["ResourceNotFoundError"]:
            if not missing_ok:
                raise

