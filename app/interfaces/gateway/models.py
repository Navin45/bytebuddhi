"""Client and manager data. Application concepts only; no terminal types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProbeResult:
    """Liveness versus readiness of a gateway URL."""

    reachable: bool
    live: bool
    ready: bool
    bytebuddhi: bool
    version: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class GatewayStatus:
    """Process state is separate from readiness to serve requests."""

    process_running: bool
    ready: bool
    live: bool
    managed: bool
    pid: int | None
    url: str
    version: str | None
    started_at: str | None
    uptime_seconds: int | None
    message: str

    def as_dict(self) -> dict[str, object]:
        return {
            "process_running": self.process_running,
            "ready": self.ready,
            "live": self.live,
            "managed": self.managed,
            "pid": self.pid,
            "url": self.url,
            "version": self.version,
            "started_at": self.started_at,
            "uptime_seconds": self.uptime_seconds,
            "message": self.message,
        }


@dataclass(frozen=True)
class HealthSnapshot:
    status: str
    service: str | None = None
    version: str | None = None
    protocol_version: int | None = None
    min_protocol_version: int | None = None


@dataclass(frozen=True)
class ReadinessSnapshot:
    status: str
    checks: dict[str, str]

    @property
    def ready(self) -> bool:
        return self.status == "ready"


@dataclass(frozen=True)
class MessageStreamResult:
    """Completed view of the current chat SSE response. Not a replay log."""

    run_id: str | None
    conversation_id: str
    content: str
    status: str
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class CancelAck:
    run_id: str
    status: str
