"""PostgreSQL durable memory store implementation using SQLAlchemy and pgvector."""

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.output.memory.memory_store import MemoryStore
from app.domain.models.memory import MemoryItem, MemoryScope, MemoryType
from app.infrastructure.config.logger import get_logger
from app.infrastructure.persistence.postgres.models import MemoryItemModel

logger = get_logger(__name__)


class PostgresMemoryStore(MemoryStore):
    """Durable memory store backed by PostgreSQL and pgvector for semantic search."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, memory: MemoryItem) -> MemoryItem:
        """Save a new memory item or update existing."""
        stmt = select(MemoryItemModel).where(
            MemoryItemModel.id == memory.id,
            MemoryItemModel.scope == memory.scope.value,
            MemoryItemModel.scope_id == memory.scope_id,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.content = memory.content
            existing.source = memory.source
            existing.importance = memory.importance  # type: ignore[assignment]
            existing.updated_at = datetime.now(UTC)
            existing.last_accessed_at = datetime.now(UTC)
            existing.expires_at = memory.expires_at
            existing.extra_metadata = memory.metadata
            if memory.embedding is not None:
                existing.embedding = memory.embedding
        else:
            model = MemoryItemModel(
                id=memory.id,
                scope=memory.scope.value,
                scope_id=memory.scope_id,
                memory_type=memory.memory_type.value,
                content=memory.content,
                source=memory.source,
                importance=memory.importance,  # type: ignore[arg-type]
                created_at=memory.created_at,
                updated_at=memory.updated_at,
                last_accessed_at=memory.last_accessed_at,
                expires_at=memory.expires_at,
                extra_metadata=memory.metadata,
                embedding=memory.embedding,
            )
            self.session.add(model)

        await self.session.flush()
        return memory

    async def get(self, memory_id: str, scope: MemoryScope, scope_id: str) -> MemoryItem | None:
        """Retrieve memory item by ID strictly within scope."""
        stmt = select(MemoryItemModel).where(
            MemoryItemModel.id == memory_id,
            MemoryItemModel.scope == scope.value,
            MemoryItemModel.scope_id == scope_id,
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            return None
        return self._to_domain(model)

    async def delete(self, memory_id: str, scope: MemoryScope, scope_id: str) -> bool:
        """Delete memory item strictly within scope."""
        stmt = (
            delete(MemoryItemModel)
            .where(
                MemoryItemModel.id == memory_id,
                MemoryItemModel.scope == scope.value,
                MemoryItemModel.scope_id == scope_id,
            )
            .returning(MemoryItemModel.id)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one_or_none() is not None

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
        """Search memory items matching filter criteria and scope boundaries."""
        now = datetime.now(UTC)

        stmt = select(MemoryItemModel).where(
            MemoryItemModel.importance >= min_importance,
            (MemoryItemModel.expires_at.is_(None) | (MemoryItemModel.expires_at > now)),
        )

        if scope is not None:
            stmt = stmt.where(MemoryItemModel.scope == scope.value)
        if scope_id is not None:
            stmt = stmt.where(MemoryItemModel.scope_id == scope_id)
        if memory_types:
            stmt = stmt.where(MemoryItemModel.memory_type.in_([mt.value for mt in memory_types]))
        if query_vector is not None and len(query_vector) == 1536:
            # Use pgvector cosine distance if query vector provided
            stmt = stmt.where(MemoryItemModel.embedding.isnot(None))
            stmt = stmt.order_by(MemoryItemModel.embedding.cosine_distance(query_vector))
        else:
            if query:
                stmt = stmt.where(MemoryItemModel.content.ilike(f"%{query}%"))
            stmt = stmt.order_by(
                MemoryItemModel.importance.desc(),
                MemoryItemModel.last_accessed_at.desc(),
            )

        stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        models = result.scalars().all()
        return [self._to_domain(m) for m in models]

    async def update(self, memory: MemoryItem) -> MemoryItem:
        """Update existing memory item."""
        memory.updated_at = datetime.now(UTC)
        return await self.save(memory)

    async def touch(self, memory_id: str) -> bool:
        """Touch last_accessed_at timestamp."""
        stmt = select(MemoryItemModel).where(MemoryItemModel.id == memory_id)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            return False
        model.last_accessed_at = datetime.now(UTC)
        await self.session.flush()
        return True

    async def cleanup_expired(self) -> int:
        """Purge expired memory items."""
        now = datetime.now(UTC)
        stmt = (
            delete(MemoryItemModel)
            .where(
                MemoryItemModel.expires_at.isnot(None),
                MemoryItemModel.expires_at <= now,
            )
            .returning(MemoryItemModel.id)
        )
        result = await self.session.execute(stmt)
        deleted = len(result.scalars().all())
        await self.session.flush()
        if deleted > 0:
            logger.info("Cleaned up expired PostgreSQL memories", count=deleted)
        return deleted

    @staticmethod
    def _to_domain(model: MemoryItemModel) -> MemoryItem:
        emb: list[float] | None = None
        if model.embedding is not None:
            emb = list(model.embedding)

        return MemoryItem(
            id=str(model.id),
            scope=MemoryScope(str(model.scope)),
            scope_id=str(model.scope_id),
            memory_type=MemoryType(str(model.memory_type)),
            content=str(model.content),
            source=str(model.source),
            importance=float(model.importance) if model.importance is not None else 0.5,
            created_at=model.created_at or datetime.now(UTC),
            updated_at=model.updated_at or datetime.now(UTC),
            last_accessed_at=model.last_accessed_at or datetime.now(UTC),
            expires_at=model.expires_at,
            metadata=dict(model.extra_metadata or {}),
            embedding=emb,
        )
