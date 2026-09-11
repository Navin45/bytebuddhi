"""Application logging port providing decoupled logging contract."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LoggerProtocol(Protocol):
    """Protocol for structured application loggers."""

    def info(self, event: str, **kwargs: Any) -> None: ...

    def warning(self, event: str, **kwargs: Any) -> None: ...

    def error(self, event: str, **kwargs: Any) -> None: ...

    def debug(self, event: str, **kwargs: Any) -> None: ...

    def exception(self, event: str, **kwargs: Any) -> None: ...


_logger_factory: Any = None


def set_logger_factory(factory: Any) -> None:
    """Register concrete logger factory from composition root."""
    global _logger_factory
    _logger_factory = factory


def get_logger(name: str) -> Any:
    """Get an application logger instance decoupled from infrastructure.

    Uses registered factory if present, otherwise dynamically uses structlog or logging.
    """
    global _logger_factory
    if _logger_factory is not None:
        return _logger_factory(name)

    try:
        import structlog

        return structlog.get_logger(name)
    except ImportError:
        import logging

        return logging.getLogger(name)
