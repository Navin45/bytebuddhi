"""Artifact storage service interface for execution logs and tool outputs."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ArtifactStore(Protocol):
    """Abstract interface for persisting execution artifacts, large outputs, and logs."""

    async def save_artifact(
        self,
        artifact_id: str,
        content: str | bytes,
        metadata: dict[str, Any] | None = None,
        project_id: str | None = None,
    ) -> str:
        """Save artifact content to storage.

        Args:
            artifact_id: Unique identifier for the artifact.
            content: Raw string or bytes content.
            metadata: Optional metadata dictionary.
            project_id: Optional project identifier for namespace isolation.

        Returns:
            str: Persistent URI or file path reference.
        """
        ...

    async def get_artifact(
        self,
        artifact_id: str,
        project_id: str | None = None,
    ) -> str | bytes | None:
        """Retrieve artifact content by identifier.

        Args:
            artifact_id: Unique identifier.
            project_id: Optional project identifier for authorization check.

        Returns:
            str | bytes | None: Content if found, None otherwise.
        """
        ...

    async def delete_artifact(
        self,
        artifact_id: str,
        project_id: str | None = None,
    ) -> bool:
        """Delete an artifact by identifier.

        Args:
            artifact_id: Unique identifier.
            project_id: Optional project identifier for authorization check.

        Returns:
            bool: True if deleted, False if not found.
        """
        ...

    async def artifact_exists(
        self,
        artifact_id: str,
        project_id: str | None = None,
    ) -> bool:
        """Check if an artifact exists."""
        ...
