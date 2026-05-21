from __future__ import annotations

import io
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import UploadFile
from azure.storage.blob import BlobSasPermissions, ContentSettings, generate_blob_sas

from backend.core.config import Settings
from backend.infra.clients import AppClients
from backend.modules.admin.models import UserAccount
from backend.modules.admin.service import AdminService
from backend.modules.resources.models import ResourceKind, ResourceRecord, UploadUrlRequest, UploadUrlResponse
from backend.modules.resources.repository import ResourceRepository


AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"}
VIDEO_EXTENSIONS = {".avi", ".mkv", ".mov", ".mp4", ".webm"}
PPT_EXTENSIONS = {".ppt", ".pptx"}
PPT_CONTENT_TYPES = {
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
MAX_SIGNATURE_BYTES = 32


class ResourceService:
    def __init__(
        self,
        repository: ResourceRepository,
        admin_service: AdminService,
        clients: AppClients,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.admin_service = admin_service
        self.clients = clients
        self.settings = settings

    async def create_upload_url(
        self,
        *,
        user: UserAccount,
        agent_id: str,
        filename: str,
        content_type: str,
        size_bytes: int,
    ) -> UploadUrlResponse:
        if not self.settings.blob_enabled or self.clients.blob_service_client is None:
            raise NotImplementedError("Direct upload requires blob storage.")

        agent = await self.admin_service.get_agent(agent_id)
        if agent is None or not agent.enabled:
            raise ValueError("Agent is not available.")
        if agent_id not in user.allowed_agent_ids:
            raise PermissionError("Agent is not enabled for this user.")

        filename = Path(filename).name
        content_type = content_type.lower()
        resource_kind = self._detect_resource_kind(filename, content_type)
        if resource_kind not in agent.accepted_resource_kinds:
            raise ValueError("This resource type is not supported by the selected agent.")

        self._validate_file_size(size_bytes)
        self._validate_declared_content_type(filename, resource_kind, content_type)

        resource_id = uuid.uuid4().hex
        blob_name = f"resources/{user.entra_object_id}/{resource_id}/{filename}"

        starts_on = datetime.now(timezone.utc) - timedelta(minutes=1)
        expires_on = datetime.now(timezone.utc) + timedelta(minutes=30)
        account_name = self._resolve_blob_account_name()

        try:
            delegation_key = await self.clients.blob_service_client.get_user_delegation_key(
                key_start_time=starts_on,
                key_expiry_time=expires_on,
            )
            sas_token = generate_blob_sas(
                account_name=account_name,
                container_name=self.settings.blob_uploads_container_name,
                blob_name=blob_name,
                user_delegation_key=delegation_key,
                permission=BlobSasPermissions(write=True, create=True),
                start=starts_on,
                expiry=expires_on,
            )
        record = ResourceRecord(
            resource_id=resource_id,
            owner_object_id=user.entra_object_id,
            agent_id=agent_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            resource_kind=resource_kind,
            storage_backend="blob",
            storage_path=blob_name,
            upload_status="pending",
        )
        await self.repository.create(record)

        base_url = self.settings.blob_account_url.rstrip("/")
        upload_url = f"{base_url}/{self.settings.blob_uploads_container_name}/{blob_name}?{sas_token}"

        return UploadUrlResponse(
            resource_id=resource_id,
            upload_url=upload_url,
            blob_path=blob_name,
            upload_expires_at=expires_on.isoformat(),
        )

    async def confirm_upload(
        self,
        *,
        owner_object_id: str,
        resource_id: str,
    ) -> ResourceRecord:
        record = await self.repository.get(owner_object_id, resource_id)
        if record is None:
            raise LookupError("Resource not found.")
        if record.upload_status != "pending":
            raise ValueError("Resource is not awaiting upload confirmation.")

        blob_client = self.clients.blob_service_client.get_blob_client(
            container=self.settings.blob_uploads_container_name,
            blob=record.storage_path,
        )

        try:
            props = await blob_client.get_blob_properties()
        except Exception:
            await self.repository.delete(owner_object_id, resource_id)
            raise ValueError("The uploaded file could not be found in storage. Upload may have failed.")

        actual_size: int = props.size
        if actual_size <= 0:
            await blob_client.delete_blob()
            await self.repository.delete(owner_object_id, resource_id)
            raise ValueError("Uploaded file is empty.")
        if actual_size > self.settings.resources_max_upload_size_bytes:
            await blob_client.delete_blob()
            await self.repository.delete(owner_object_id, resource_id)
            raise ValueError("Uploaded file exceeds the maximum allowed size.")

        if self.settings.resources_enable_signature_validation:
            try:
                stream = await blob_client.download_blob(offset=0, length=MAX_SIGNATURE_BYTES)
                signature = await stream.readall()
            except Exception:
                await self.repository.delete(owner_object_id, resource_id)
                raise ValueError("Could not read the uploaded file for validation.")
            try:
                self._validate_resource_signature(record.filename, record.resource_kind, signature)
            except ValueError:
                await blob_client.delete_blob()
                await self.repository.delete(owner_object_id, resource_id)
                raise

        updated = await self.repository.update_upload_status(
            owner_object_id, resource_id, "ready", size_bytes=actual_size
        )
        if updated is None:
            raise LookupError("Resource not found.")
        return updated

    async def upload_resource(
        self,
        *,
        user: UserAccount,
        agent_id: str,
        upload: UploadFile,
    ) -> ResourceRecord:
        agent = await self.admin_service.get_agent(agent_id)
        if agent is None or not agent.enabled:
            raise ValueError("Agent is not available.")
        if agent_id not in user.allowed_agent_ids:
            raise PermissionError("Agent is not enabled for this user.")

        filename = Path(upload.filename or "resource").name
        content_type = (upload.content_type or "application/octet-stream").lower()
        resource_kind = self._detect_resource_kind(filename, content_type)
        if resource_kind not in agent.accepted_resource_kinds:
            raise ValueError("This resource type is not supported by the selected agent.")
        resource_id = uuid.uuid4().hex
        size_bytes = self._get_file_size(upload)
        self._validate_file_size(size_bytes)
        signature = self._read_file_signature(upload)
        self._validate_resource_signature(filename, resource_kind, signature)
        self._validate_declared_content_type(filename, resource_kind, content_type)
        self._run_basic_security_scan(filename, signature)

        storage_backend: str
        storage_path: str
        if self.clients.blob_service_client is not None and self.settings.blob_enabled:
            storage_backend = "blob"
            storage_path = await self._upload_to_blob(user.entra_object_id, resource_id, filename, upload)
        else:
            storage_backend = "local"
            storage_path = self._upload_to_local(user.entra_object_id, resource_id, filename, upload)

        record = ResourceRecord(
            resource_id=resource_id,
            owner_object_id=user.entra_object_id,
            agent_id=agent_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            resource_kind=resource_kind,
            storage_backend=storage_backend,  # type: ignore[arg-type]
            storage_path=storage_path,
        )
        return await self.repository.create(record)

    async def list_resources(self, *, owner_object_id: str, agent_id: str | None = None) -> list[ResourceRecord]:
        return await self.repository.list_for_owner(owner_object_id, agent_id=agent_id)

    async def get_resource(self, *, owner_object_id: str, resource_id: str) -> ResourceRecord | None:
        return await self.repository.get(owner_object_id, resource_id)

    async def download_resource_to_directory(
        self,
        *,
        record: ResourceRecord,
        destination_dir: str | Path,
    ) -> str:
        destination_root = Path(destination_dir).expanduser().resolve()
        destination_root.mkdir(parents=True, exist_ok=True)
        destination = destination_root / record.filename
        if record.storage_backend == "local":
            source = Path(record.storage_path).expanduser().resolve()
            destination.write_bytes(source.read_bytes())
            return str(destination)

        blob_client = self.clients.blob_service_client.get_blob_client(
            container=self.settings.blob_uploads_container_name,
            blob=record.storage_path,
        )
        stream = await blob_client.download_blob()
        destination.write_bytes(await stream.readall())
        return str(destination)

    async def read_resource_content(self, *, record: ResourceRecord) -> bytes:
        if record.storage_backend == "local":
            source = Path(record.storage_path).expanduser().resolve()
            return source.read_bytes()

        blob_client = self.clients.blob_service_client.get_blob_client(
            container=self.settings.blob_uploads_container_name,
            blob=record.storage_path,
        )
        stream = await blob_client.download_blob()
        return await stream.readall()

    async def get_resource_preview_url(self, *, record: ResourceRecord, expires_minutes: int = 15) -> str | None:
        if record.storage_backend != "blob" or self.clients.blob_service_client is None:
            return None

        starts_on = datetime.now(timezone.utc) - timedelta(minutes=1)
        expires_on = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
        account_name = self._resolve_blob_account_name()

        try:
            delegation_key = await self.clients.blob_service_client.get_user_delegation_key(
                key_start_time=starts_on,
                key_expiry_time=expires_on,
            )
            sas_token = generate_blob_sas(
                account_name=account_name,
                container_name=self.settings.blob_uploads_container_name,
                blob_name=record.storage_path,
                user_delegation_key=delegation_key,
                permission=BlobSasPermissions(read=True),
                start=starts_on,
                expiry=expires_on,
                content_type=record.content_type,
            )
        base_url = self.settings.blob_account_url.rstrip("/")
        return f"{base_url}/{self.settings.blob_uploads_container_name}/{record.storage_path}?{sas_token}"

    def _detect_resource_kind(self, filename: str, content_type: str) -> ResourceKind:
        suffix = Path(filename).suffix.lower()
        if suffix in AUDIO_EXTENSIONS or content_type.startswith("audio/"):
            return "audio"
        if suffix in VIDEO_EXTENSIONS or content_type.startswith("video/"):
            return "video"
        if suffix in PPT_EXTENSIONS or content_type in PPT_CONTENT_TYPES:
            return "ppt"
        raise ValueError("Unsupported resource type. Only audio, video, and PowerPoint are allowed.")

    def _get_file_size(self, upload: UploadFile) -> int:
        upload.file.seek(0, os.SEEK_END)
        size_bytes = upload.file.tell()
        upload.file.seek(0)
        return size_bytes

    def _validate_file_size(self, size_bytes: int) -> None:
        if size_bytes <= 0:
            raise ValueError("Uploaded file is empty.")
        if size_bytes > self.settings.resources_max_upload_size_bytes:
            raise ValueError("Uploaded file exceeds the maximum allowed size.")

    def _read_file_signature(self, upload: UploadFile) -> bytes:
        upload.file.seek(0)
        signature = upload.file.read(MAX_SIGNATURE_BYTES)
        upload.file.seek(0)
        return signature

    def _validate_resource_signature(self, filename: str, resource_kind: ResourceKind, signature: bytes) -> None:
        if not self.settings.resources_enable_signature_validation:
            return
        suffix = Path(filename).suffix.lower()
        if resource_kind == "audio":
            if suffix == ".wav" and not signature.startswith(b"RIFF"):
                raise ValueError("Invalid WAV file signature.")
            if suffix == ".flac" and not signature.startswith(b"fLaC"):
                raise ValueError("Invalid FLAC file signature.")
            if suffix == ".ogg" and not signature.startswith(b"OggS"):
                raise ValueError("Invalid OGG file signature.")
            if suffix == ".mp3" and not (signature.startswith(b"ID3") or (len(signature) >= 2 and signature[0] == 0xFF)):
                raise ValueError("Invalid MP3 file signature.")
        if resource_kind == "video":
            if suffix in {".mp4", ".mov", ".m4v"} and b"ftyp" not in signature:
                raise ValueError("Invalid MP4/MOV file signature.")
            if suffix == ".avi" and not signature.startswith(b"RIFF"):
                raise ValueError("Invalid AVI file signature.")
            if suffix == ".mkv" and not signature.startswith(b"\x1A\x45\xDF\xA3"):
                raise ValueError("Invalid MKV file signature.")
            if suffix == ".webm" and not signature.startswith(b"\x1A\x45\xDF\xA3"):
                raise ValueError("Invalid WebM file signature.")
        if resource_kind == "ppt":
            if suffix == ".pptx" and not signature.startswith(b"PK"):
                raise ValueError("Invalid PPTX file signature.")
            if suffix == ".ppt" and not signature.startswith(b"\xD0\xCF\x11\xE0"):
                raise ValueError("Invalid PPT file signature.")

    def _validate_declared_content_type(self, filename: str, resource_kind: ResourceKind, content_type: str) -> None:
        suffix = Path(filename).suffix.lower()
        if resource_kind == "audio" and not (content_type.startswith("audio/") or suffix in AUDIO_EXTENSIONS):
            raise ValueError("Declared content type does not match an audio file.")
        if resource_kind == "video" and not (content_type.startswith("video/") or suffix in VIDEO_EXTENSIONS):
            raise ValueError("Declared content type does not match a video file.")
        if resource_kind == "ppt" and not (content_type in PPT_CONTENT_TYPES or suffix in PPT_EXTENSIONS):
            raise ValueError("Declared content type does not match a PowerPoint file.")

    def _run_basic_security_scan(self, filename: str, signature: bytes) -> None:
        if not self.settings.resources_enable_malware_scan:
            return
        _ = io.BytesIO(signature)
        _ = filename
        raise NotImplementedError("External malware scanning is not configured yet.")

    async def _upload_to_blob(self, owner_object_id: str, resource_id: str, filename: str, upload: UploadFile) -> str:
        blob_name = f"resources/{owner_object_id}/{resource_id}/{filename}"
        blob_client = self.clients.blob_service_client.get_blob_client(
            container=self.settings.blob_uploads_container_name,
            blob=blob_name,
        )
        upload.file.seek(0)
        await blob_client.upload_blob(
            upload.file,
            overwrite=True,
            content_settings=ContentSettings(content_type=upload.content_type or "application/octet-stream"),
        )
        return blob_name

    def _upload_to_local(self, owner_object_id: str, resource_id: str, filename: str, upload: UploadFile) -> str:
        base_dir = Path(self.settings.local_storage_path).expanduser().resolve()
        destination = base_dir / "resources" / owner_object_id / resource_id / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        upload.file.seek(0)
        with destination.open("wb") as handle:
            shutil.copyfileobj(upload.file, handle)
        return str(destination)

    def _resolve_blob_account_name(self) -> str:
        if not self.settings.blob_account_url:
            raise ValueError("Blob account URL is not configured.")
        hostname = urlsplit(self.settings.blob_account_url).hostname or ""
        account_name = hostname.split(".")[0]
        if not account_name:
            raise ValueError("Unable to resolve blob account name.")
        return account_name

