"""PII-safe logging setup and correlation-id plumbing (TODO D).

The correlation id for the current request lives in a contextvar so any log record can carry it
without threading it through call signatures. Per CLAUDE.md, callers must log only ids / types /
counts — never PII values, and only `type(exc).__name__` for exceptions.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

# Set by the correlation-id middleware; read by the log filter below.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Inject the current request id onto every record as `%(request_id)s`."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logging once with a request-id-aware formatter."""
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
