"""StrongChat structured (JSONL) logging setup.

Replaces every previous SQLite ``messages`` row insert with one JSON record
per event. Cross-process safe via :class:`ConcurrentRotatingFileHandler`
(``fcntl`` advisory lock, atomic rotation). Levels:

* ``ERROR`` (default when env unset): exceptions and retry-exhausted failures.
* ``INFO``: one record per pipeline step with ``event``, ``elapsed_ms``,
  ``status``.
* ``DEBUG``: full audit (``prompt``, ``raw_response``, embedded texts, context
  bundle payloads) — equivalent field set to the old ``messages`` table.

Record shape (one JSON object per line, fields differ by event):

    {"ts":"2026-08-16T12:00:00.123Z","level":"INFO",
     "correlation_id":"8f3e...","event":"intent_generation","slug":"intent_generation",
     "elapsed_ms":420,"status":"ok"}
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from logging import LogRecord
from typing import Any, Dict, Optional

try:
    from concurrent_log_handler import ConcurrentRotatingFileHandler
except ImportError:
    # Fall back to a standard FileHandler so imports don't crash when the
    # extra dependency isn't installed yet. Cross-process safety is lost but
    # tests and dev loops still work. requirements.txt pins it for production.
    ConcurrentRotatingFileHandler = None
    import logging as _stdlog
    from logging import FileHandler as _FallbackFileHandler

DEFAULT_LOG_FILE = os.path.join("data", "logs", "strongchat.log")
DEFAULT_LEVEL = "ERROR"
MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5


class JsonFormatter(logging.Formatter):
    """One JSON object per log record, with extras merged in."""

    _RESERVED = set(logging.LogRecord(
        "", 0, "", 0, "", None, None
    ).__dict__.keys()) | {"message", "asctime"}

    def format(self, record: LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key in payload:
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def _resolve_level(level_name: str) -> int:
    upper = (level_name or "").upper()
    levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return levels.get(upper, logging.ERROR)


def configure_logging(
    level: Optional[str] = None,
    log_file: Optional[str] = None,
) -> logging.Logger:
    """Set up the root ``strongchat`` logger with the JSONL handler.

    Reads env at startup. Idempotent — calling twice re-uses the existing
    handler without stacking duplicates. The agent never controls these
    values; they come from the environment the server owner sets.
    """
    env_level = level or os.getenv("STRONGCHAT_LOG_LEVEL", DEFAULT_LEVEL)
    env_file = log_file or os.getenv("STRONGCHAT_LOG_FILE", DEFAULT_LOG_FILE)

    log_dir = os.path.dirname(env_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("strongchat")
    logger.setLevel(_resolve_level(env_level))
    logger.propagate = False

    if getattr(logger, "_strongchat_configured", False):
        return logger

    if ConcurrentRotatingFileHandler is not None:
        handler: logging.Handler = ConcurrentRotatingFileHandler(
            env_file, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
    else:
        handler = _FallbackFileHandler(env_file, encoding="utf-8")

    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    # Always send ERROR-level to stderr so the server surfaces hard failures
    # even when the agent doesn't tail the log file.
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    # Plain formatter on stderr keeps it readable for operators.
    stderr_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(stderr_handler)

    logger._strongchat_configured = True  # type: ignore[attr-defined]
    return logger


def get_logger(name: str = "strongchat") -> logging.Logger:
    """Return a child logger under the configured ``strongchat`` root.

    ``configure_logging()`` must be called at startup (typically from
    ``server.py``) for the JSONL handler to be live. Without it, log records
    fall through to the default stderr handler only at WARNING+.

    Names not already prefixed with ``strongchat`` are coerced into the
    ``strongchat`` hierarchy so ``assertLogs("strongchat", ...)`` and the
    JSONL handler on the root both see every record from any child.
    """
    configure_logging()
    if name != "strongchat" and not name.startswith("strongchat."):
        name = f"strongchat.{name}"
    return logging.getLogger(name)