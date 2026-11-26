"""Structured JSON logging.

Logs are written to stdout as one JSON object per line so that a container
runtime (Docker, journald, CloudWatch, Loki) can collect them without a
sidecar parser. Twelve-factor: the app never writes log files itself.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

EXTRA_FIELDS = (
    "event",
    "request_id",
    "method",
    "path",
    "status",
    "duration_ms",
    "user",
    "ticket_id",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in EXTRA_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(app) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(app.config.get("LOG_LEVEL", "INFO"))

    app.logger.handlers = [handler]
    app.logger.propagate = False
    app.logger.setLevel(app.config.get("LOG_LEVEL", "INFO"))

    # Werkzeug's dev server access log duplicates our own request log.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
