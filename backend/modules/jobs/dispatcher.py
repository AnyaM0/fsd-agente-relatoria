from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from backend.core.config import Settings
from backend.infra.clients import AppClients

try:
    from azure.servicebus import ServiceBusMessage
except ImportError:  # pragma: no cover
    ServiceBusMessage = None  # type: ignore[assignment]


@dataclass(frozen=True)
class JobDispatchResult:
    backend: str
    reference: str | None = None


class JobDispatcher(ABC):
    @abstractmethod
    async def dispatch(self, payload: dict, *, delay_seconds: int | None = None) -> JobDispatchResult: ...


class NoopJobDispatcher(JobDispatcher):
    async def dispatch(self, payload: dict, *, delay_seconds: int | None = None) -> JobDispatchResult:
        _ = payload
        _ = delay_seconds
        return JobDispatchResult(backend="noop", reference=None)


class ServiceBusJobDispatcher(JobDispatcher):
    def __init__(self, clients: AppClients, settings: Settings) -> None:
        if clients.servicebus_client is None:
            raise ValueError("Service Bus client is not configured.")
        if ServiceBusMessage is None:
            raise RuntimeError("azure-servicebus is not installed.")
        self._servicebus_client = clients.servicebus_client
        self._queue_name = settings.servicebus_jobs_queue_name

    async def dispatch(self, payload: dict, *, delay_seconds: int | None = None) -> JobDispatchResult:
        scheduled_enqueue_time_utc = None
        if delay_seconds and delay_seconds > 0:
            scheduled_enqueue_time_utc = datetime.now(UTC) + timedelta(seconds=delay_seconds)
        async with self._servicebus_client.get_queue_sender(queue_name=self._queue_name) as sender:
            message = ServiceBusMessage(
                json.dumps(payload),
                scheduled_enqueue_time_utc=scheduled_enqueue_time_utc,
            )
            await sender.send_messages(message)
        return JobDispatchResult(backend="service_bus", reference=self._queue_name)


def create_job_dispatcher(settings: Settings, clients: AppClients) -> JobDispatcher:
    if settings.servicebus_enabled and clients.servicebus_client is not None:
        return ServiceBusJobDispatcher(clients, settings)
    return NoopJobDispatcher()
