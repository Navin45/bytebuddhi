"""MemoryStore protocol defining the persistence port for memory storage."""

from typing import Protocol, runtime_checkable

from app.domain.models.memory import MemoryItem, MemoryScope, MemoryType


@runtime_checkable
class MemoryStore(Protocol):
    """Abstract port for memory persistence backends (SQLite, PostgreSQL, etc.)."""

    async def save(self, memory: MemoryItem) -> MemoryItem:
        """Save a new memory item or overwrite if ID exists."""
        ...

    async def get(self, memory_id: str, scope: MemoryScope, scope_id: str) -> MemoryItem | None:
        """Retrieve a memory item by ID enforcing scope boundary."""
        ...

    async def delete(self, memory_id: str, scope: MemoryScope, scope_id: str) -> bool:
        """Delete a memory item enforcing scope boundary."""
        ...

    async def search(
        self,
        query: str | None = None,
        scope: MemoryScope | None = None,
        scope_id: str | None = None,
        memory_types: list[MemoryType] | None = None,
        min_importance: float = 0.0,
        limit: int = 10,
        query_vector: list[float] | None = None,
    ) -> list[MemoryItem]:
        """Search memory items matching filter criteria and scope boundaries.

        Args:
            query: Keyword text query.
            scope: Target MemoryScope constraint.
            scope_id: Target scope identifier.
            memory_types: Filter to specific memory types.
            min_importance: Minimum importance threshold.
            limit: Maximum items to return.
            query_vector: Optional vector embedding for semantic search.

        Returns:
            list[MemoryItem]: Bounded list of matching memory items.
        """
        ...

    async def update(self, memory: MemoryItem) -> MemoryItem:
        """Update existing memory content, importance, or metadata."""
        ...

    async def touch(self, memory_id: str) -> bool:
        """Update last_accessed_at timestamp on a memory item."""
        ...

    async def cleanup_expired(self) -> int:
        """Purge expired memory items and return count of deleted entries."""
        ...
