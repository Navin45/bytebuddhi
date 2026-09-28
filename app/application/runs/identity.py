"""Process-instance identity. A PID alone collides across hosts."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from app.application.runs.store import utc_now


@dataclass(frozen=True)
class WorkerIdentity:
    instance_id: str
    process_id: int
    started_at: datetime

    @classmethod
    def create(cls) -> WorkerIdentity:
        return cls(instance_id=str(uuid4()), process_id=os.getpid(), started_at=utc_now())

    @property
    def worker_id(self) -> str:
        return f"{self.instance_id}:{self.process_id}"
