import logging
import re
import sys
from typing import Any

import structlog

from app.infrastructure.config.settings import settings

_OAUTH_QUERY_RE = re.compile(r"([?&](?:code|state|error_description)=)[^&\s]+", re.IGNORECASE)


class OauthQueryRedactingFilter(logging.Filter):
    """Strip OAuth callback secrets from access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _OAUTH_QUERY_RE.sub(r"\1[REDACTED]", record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: _OAUTH_QUERY_RE.sub(r"\1[REDACTED]", value) if isinstance(value, str) else value
                    for key, value in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    _OAUTH_QUERY_RE.sub(r"\1[REDACTED]", arg) if isinstance(arg, str) else arg for arg in record.args
                )
        return True


def setup_logging(stream: Any | None = None, level: str | None = None) -> None:
    """Setup structured logging.

    Args:
        stream: Destination for log records. Defaults to stdout for the API.
            The CLI passes stderr so JSON results on stdout stay uncorrupted.
        level: Optional log level name. Defaults to settings.log_level.
    """
    log_stream = stream if stream is not None else sys.stdout
    log_level = (level or settings.log_level).upper()

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if settings.debug else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(log_level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=log_stream),
        cache_logger_on_first_use=False,
    )

    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=log_stream,
        level=getattr(logging, log_level, logging.INFO),
        force=True,
    )
    redactor = OauthQueryRedactingFilter()
    logging.getLogger().addFilter(redactor)
    logging.getLogger("uvicorn.access").addFilter(redactor)


def get_logger(name: str) -> Any:
    """Get a logger instance."""
    return structlog.get_logger(name)
