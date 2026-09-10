"""Artifact metadata and domain entity for ByteBuddhi."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass
class Artifact:
    """Domain model representing a persistent execution artifact or log file."""

    id: str
    artifact_type: str  # "command_stdout", "command_stderr", "diff", "patch", "report"
    size_bytes: int
    storage_ref: str  # Absolute file path or persistent URI
    mime_type: str = "text/plain"
    source_execution_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    summary: str | None = None
    preview: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        artifact_type: str,
        size_bytes: int,
        storage_ref: str,
        artifact_id: str | None = None,
        mime_type: str = "text/plain",
        source_execution_id: str | None = None,
        summary: str | None = None,
        preview: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Artifact":
        """Factory constructor for Artifact domain entity."""
        return cls(
            id=artifact_id or f"art_{uuid4().hex[:12]}",
            artifact_type=artifact_type,
            size_bytes=size_bytes,
            storage_ref=storage_ref,
            mime_type=mime_type,
            source_execution_id=source_execution_id,
            created_at=datetime.now(UTC),
            summary=summary,
            preview=preview,
            metadata=metadata or {},
        )

    def to_context_dict(self) -> dict[str, Any]:
        """Convert artifact to a lightweight representation suitable for model context."""
        return {
            "artifact_id": self.id,
            "type": self.artifact_type,
            "size_bytes": self.size_bytes,
            "summary": self.summary or f"Artifact of type {self.artifact_type} ({self.size_bytes} bytes)",
            "preview": self.preview or "",
            "storage_ref": self.storage_ref,
        }
