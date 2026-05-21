from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("job_id", "request_id", "event"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(*, debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    if getattr(root, "_fsd_backend_logging_configured", False):
        return
    root.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers.clear()
    root.addHandler(handler)
    root._fsd_backend_logging_configured = True  # type: ignore[attr-defined]
