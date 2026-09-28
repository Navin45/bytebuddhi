"""SQLite LangGraph checkpoint saver for the standalone profile."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)

from app.infrastructure.persistence.sqlite.database import transaction


class SqliteCheckpointSaver(BaseCheckpointSaver):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        if not thread_id:
            return None
        checkpoint_id = configurable.get("checkpoint_id")
        with transaction(self.path) as connection:
            if checkpoint_id:
                row = connection.execute(
                    """
                    SELECT * FROM agent_checkpoints
                    WHERE thread_id = ? AND checkpoint_id = ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (str(thread_id), str(checkpoint_id)),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM agent_checkpoints WHERE thread_id = ? ORDER BY created_at DESC LIMIT 1",
                    (str(thread_id),),
                ).fetchone()
        if row is None:
            return None
        return self._tuple(row, config)

    async def aget(self, config: RunnableConfig) -> Checkpoint | None:
        found = await self.aget_tuple(config)
        return found.checkpoint if found else None

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        del new_versions
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        if not thread_id:
            return config
        checkpoint_id = checkpoint["id"]
        type_c, bytes_c = self.serde.dumps_typed(checkpoint)
        type_m, bytes_m = self.serde.dumps_typed(metadata)
        payload = {
            "checkpoint": {"type": type_c, "data": bytes_c.hex()},
            "metadata": {"type": type_m, "data": bytes_m.hex()},
        }
        parent_id = configurable.get("checkpoint_id")
        with transaction(self.path) as connection:
            connection.execute(
                """
                INSERT INTO agent_checkpoints (
                    id, thread_id, checkpoint_id, parent_checkpoint_id, checkpoint_data, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    str(thread_id),
                    str(checkpoint_id),
                    str(parent_id) if parent_id else None,
                    json.dumps(payload),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return {
            "configurable": {
                **configurable,
                "thread_id": str(thread_id),
                "checkpoint_id": str(checkpoint_id),
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        del config, writes, task_id, task_path

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        del filter, before
        thread_id = None
        if config is not None:
            thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id or config is None:
            return
        sql = "SELECT * FROM agent_checkpoints WHERE thread_id = ? ORDER BY created_at DESC"
        params: list[object] = [str(thread_id)]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with transaction(self.path) as connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        for row in rows:
            yield self._tuple(row, config)

    def _tuple(self, row, config: RunnableConfig) -> CheckpointTuple:
        payload = json.loads(row["checkpoint_data"])
        checkpoint = self.serde.loads_typed(
            (payload["checkpoint"]["type"], bytes.fromhex(payload["checkpoint"]["data"]))
        )
        metadata = self.serde.loads_typed((payload["metadata"]["type"], bytes.fromhex(payload["metadata"]["data"])))
        parent_config: RunnableConfig | None = None
        if row["parent_checkpoint_id"]:
            parent_config = cast(
                RunnableConfig,
                {
                    "configurable": {
                        "thread_id": row["thread_id"],
                        "checkpoint_id": row["parent_checkpoint_id"],
                    }
                },
            )
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": row["thread_id"],
                    "checkpoint_id": row["checkpoint_id"],
                    "checkpoint_ns": config.get("configurable", {}).get("checkpoint_ns", ""),
                }
            },
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=[],
        )
