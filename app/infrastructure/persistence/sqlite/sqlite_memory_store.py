"""SQLite operational memory store for working memory and execution observations."""

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.application.ports.output.memory.memory_store import MemoryStore
from app.domain.models.memory import MemoryItem, MemoryScope, MemoryType
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class SqliteMemoryStore(MemoryStore):
    """Local SQLite memory store operating in WAL mode for operational and working memory."""

    def __init__(self, db_path: str | Path = "./storage/operational_memory.db"):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create and configure a SQLite connection with WAL mode and busy timeout."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        """Initialize operational database schema."""
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS operational_memories (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    importance REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_accessed_at TEXT NOT NULL,
                    expires_at TEXT,
                    metadata TEXT,
                    embedding TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_op_mem_scope ON operational_memories(scope, scope_id);
                CREATE INDEX IF NOT EXISTS idx_op_mem_type ON operational_memories(memory_type);
                CREATE INDEX IF NOT EXISTS idx_op_mem_expires ON operational_memories(expires_at);
                """
            )

    async def save(self, memory: MemoryItem) -> MemoryItem:
        """Save or replace a memory item."""
        return await asyncio.to_thread(self._sync_save, memory)

    def _sync_save(self, memory: MemoryItem) -> MemoryItem:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO operational_memories (
                    id, scope, scope_id, memory_type, content, source,
                    importance, created_at, updated_at, last_accessed_at,
                    expires_at, metadata, embedding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.id,
                    memory.scope.value,
                    memory.scope_id,
                    memory.memory_type.value,
                    memory.content,
                    memory.source,
                    memory.importance,
                    memory.created_at.isoformat(),
                    memory.updated_at.isoformat(),
                    memory.last_accessed_at.isoformat(),
                    memory.expires_at.isoformat() if memory.expires_at else None,
                    json.dumps(memory.metadata),
                    json.dumps(memory.embedding) if memory.embedding else None,
                ),
            )
        return memory

    async def get(self, memory_id: str, scope: MemoryScope, scope_id: str) -> MemoryItem | None:
        """Get memory item by ID enforcing scope boundary."""
        return await asyncio.to_thread(self._sync_get, memory_id, scope, scope_id)

    def _sync_get(self, memory_id: str, scope: MemoryScope, scope_id: str) -> MemoryItem | None:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM operational_memories
                WHERE id = ? AND scope = ? AND scope_id = ?
                """,
                (memory_id, scope.value, scope_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_memory(row)

    async def delete(self, memory_id: str, scope: MemoryScope, scope_id: str) -> bool:
        """Delete memory item by ID enforcing scope boundary."""
        return await asyncio.to_thread(self._sync_delete, memory_id, scope, scope_id)

    def _sync_delete(self, memory_id: str, scope: MemoryScope, scope_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM operational_memories
                WHERE id = ? AND scope = ? AND scope_id = ?
                """,
                (memory_id, scope.value, scope_id),
            )
            return cursor.rowcount > 0

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
        return await asyncio.to_thread(self._sync_search, query, scope, scope_id, memory_types, min_importance, limit)

    def _sync_search(
        self,
        query: str | None = None,
        scope: MemoryScope | None = None,
        scope_id: str | None = None,
        memory_types: list[MemoryType] | None = None,
        min_importance: float = 0.0,
        limit: int = 10,
    ) -> list[MemoryItem]:
        conditions = ["importance >= ?"]
        params: list[object] = [min_importance]

        # Automatic expiration filtering
        now_iso = datetime.now(UTC).isoformat()
        conditions.append("(expires_at IS NULL OR expires_at > ?)")
        params.append(now_iso)

        if scope is not None:
            conditions.append("scope = ?")
            params.append(scope.value)

        if scope_id is not None:
            conditions.append("scope_id = ?")
            params.append(scope_id)

        if memory_types:
            placeholders = ",".join("?" for _ in memory_types)
            conditions.append(f"memory_type IN ({placeholders})")
            params.extend(mt.value for mt in memory_types)

        if query:
            conditions.append("content LIKE ?")
            params.append(f"%{query}%")

        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT * FROM operational_memories
            WHERE {where_clause}
            ORDER BY importance DESC, last_accessed_at DESC
            LIMIT ?
        """
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()
            return [self._row_to_memory(r) for r in rows]

    async def update(self, memory: MemoryItem) -> MemoryItem:
        """Update existing memory item."""
        memory.updated_at = datetime.now(UTC)
        return await self.save(memory)

    async def touch(self, memory_id: str) -> bool:
        """Touch last_accessed_at timestamp."""
        return await asyncio.to_thread(self._sync_touch, memory_id)

    def _sync_touch(self, memory_id: str) -> bool:
        now_iso = datetime.now(UTC).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE operational_memories
                SET last_accessed_at = ?
                WHERE id = ?
                """,
                (now_iso, memory_id),
            )
            return cursor.rowcount > 0

    async def cleanup_expired(self) -> int:
        """Delete all expired memories."""
        return await asyncio.to_thread(self._sync_cleanup_expired)

    def _sync_cleanup_expired(self) -> int:
        now_iso = datetime.now(UTC).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM operational_memories
                WHERE expires_at IS NOT NULL AND expires_at <= ?
                """,
                (now_iso,),
            )
            deleted = cursor.rowcount
            if deleted > 0:
                logger.info("Cleaned up expired operational memories", count=deleted)
            return deleted

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> MemoryItem:
        expires = datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        emb = json.loads(row["embedding"]) if row["embedding"] else None

        return MemoryItem(
            id=row["id"],
            scope=MemoryScope(row["scope"]),
            scope_id=row["scope_id"],
            memory_type=MemoryType(row["memory_type"]),
            content=row["content"],
            source=row["source"],
            importance=float(row["importance"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_accessed_at=datetime.fromisoformat(row["last_accessed_at"]),
            expires_at=expires,
            metadata=meta,
            embedding=emb,
        )
