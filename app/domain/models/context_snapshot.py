"""ContextSnapshot reference entity for model decision auditing and provenance."""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.domain.models.context import ModelContext


@dataclass
class ContextSnapshot:
    """Lightweight audit snapshot capturing exact references of context supplied to an LLM."""

    snapshot_id: str
    run_id: str
    iteration: int
    system_prompt_hash: str
    message_ids: list[str] = field(default_factory=list)
    memory_ids: list[str] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    tool_schema_hash: str = ""
    total_estimated_tokens: int = 0
    truncated_sections: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_model_context(
        cls,
        run_id: str,
        iteration: int,
        model_context: ModelContext,
        snapshot_id: str | None = None,
    ) -> "ContextSnapshot":
        """Construct a lightweight snapshot from a ModelContext without duplicating payloads."""
        sys_hash = hashlib.sha256(model_context.system_prompt.encode("utf-8")).hexdigest()[:16]

        tool_str = "".join(sorted(t.get("name", "") for t in model_context.tool_definitions))
        tool_hash = hashlib.sha256(tool_str.encode("utf-8")).hexdigest()[:16] if tool_str else ""

        # Extract memory IDs
        mem_ids = [m.id for m in model_context.memories]

        # Extract artifact IDs
        art_ids = [a.get("artifact_id", "") for a in model_context.artifact_references if a.get("artifact_id")]

        # Extract message identifiers or index positions
        msg_ids = [m.get("tool_call_id") or f"msg_{i}" for i, m in enumerate(model_context.messages)]

        return cls(
            snapshot_id=snapshot_id or f"snap_{uuid4().hex[:12]}",
            run_id=run_id,
            iteration=iteration,
            system_prompt_hash=sys_hash,
            message_ids=msg_ids,
            memory_ids=mem_ids,
            artifact_ids=art_ids,
            tool_schema_hash=tool_hash,
            total_estimated_tokens=model_context.estimated_tokens,
            truncated_sections=list(model_context.truncated_sections),
            created_at=datetime.now(UTC),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert snapshot to dictionary for persistence or telemetry."""
        return {
            "snapshot_id": self.snapshot_id,
            "run_id": self.run_id,
            "iteration": self.iteration,
            "system_prompt_hash": self.system_prompt_hash,
            "message_ids": self.message_ids,
            "memory_ids": self.memory_ids,
            "artifact_ids": self.artifact_ids,
            "tool_schema_hash": self.tool_schema_hash,
            "total_estimated_tokens": self.total_estimated_tokens,
            "truncated_sections": self.truncated_sections,
            "created_at": self.created_at.isoformat(),
        }
