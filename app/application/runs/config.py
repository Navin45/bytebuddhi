"""Run execution settings. Values are validated before a worker starts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunExecutionConfig:
    max_active_runs: int = 20
    heartbeat_seconds: float = 15.0
    lease_timeout_seconds: float = 120.0
    reaper_interval_seconds: float = 30.0
    shutdown_grace_seconds: float = 30.0
    reaper_batch_size: int = 20
    heartbeat_retries: int = 3

    def validate(self) -> None:
        if self.max_active_runs < 1:
            raise ValueError("max_active_runs must be >= 1")
        if self.heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be > 0")
        if self.lease_timeout_seconds <= self.heartbeat_seconds:
            raise ValueError("lease_timeout_seconds must be greater than heartbeat_seconds")
        if self.reaper_interval_seconds <= 0:
            raise ValueError("reaper_interval_seconds must be > 0")
        if self.shutdown_grace_seconds < 0:
            raise ValueError("shutdown_grace_seconds must be >= 0")
        if self.reaper_batch_size < 1:
            raise ValueError("reaper_batch_size must be >= 1")
        if self.heartbeat_retries < 1:
            raise ValueError("heartbeat_retries must be >= 1")
