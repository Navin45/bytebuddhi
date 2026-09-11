"""PostgreSQL checkpoint saver for LangGraph.

This module implements a checkpoint saver that stores LangGraph agent
state in PostgreSQL, enabling conversation persistence and resumption.
"""

import json
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import Any
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from sqlalchemy import DateTime, String, Text, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.config.logger import get_logger
from app.infrastructure.persistence.postgres.database import Base

logger = get_logger(__name__)


class CheckpointModel(Base):
    """SQLAlchemy model for storing agent checkpoints.

    This model stores the state of the LangGraph agent at various
    points during execution, enabling conversation resumption and
    state recovery.

    Attributes:
        id: Unique checkpoint identifier
        thread_id: Conversation/thread identifier
        checkpoint_id: LangGraph checkpoint ID
        parent_checkpoint_id: Parent checkpoint for branching
        checkpoint_data: Serialized checkpoint state (JSON)
        created_at: Checkpoint creation timestamp
    """

    __tablename__ = "agent_checkpoints"

    id: Mapped[str] = mapped_column(String(255), primary_key=True, default=lambda: str(uuid4()))
    thread_id: Mapped[str] = mapped_column(String(255), index=True)
    checkpoint_id: Mapped[str] = mapped_column(String(255), unique=True)
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checkpoint_data: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PostgresCheckpointSaver(BaseCheckpointSaver):
    """PostgreSQL-based checkpoint saver for LangGraph.

    This class implements the BaseCheckpointSaver interface to store
    and retrieve agent checkpoints from PostgreSQL with parameterized queries.
    """

    def __init__(self, session: AsyncSession):
        """Initialize checkpoint saver with database session.

        Args:
            session: SQLAlchemy async session for database operations
        """
        super().__init__()
        self.session = session

    def _model_to_tuple(
        self,
        model: CheckpointModel,
        config: RunnableConfig,
    ) -> CheckpointTuple:
        """Convert a CheckpointModel to a CheckpointTuple."""
        raw_data = json.loads(model.checkpoint_data)
        if "checkpoint" in raw_data and isinstance(raw_data["checkpoint"], dict):
            c_typed = (
                raw_data["checkpoint"]["type"],
                bytes.fromhex(raw_data["checkpoint"]["data"]),
            )
            checkpoint = self.serde.loads_typed(c_typed)
            m_typed = (
                (
                    raw_data["metadata"]["type"],
                    bytes.fromhex(raw_data["metadata"]["data"]),
                )
                if "metadata" in raw_data and isinstance(raw_data["metadata"], dict)
                else ("json", b"{}")
            )
            metadata = self.serde.loads_typed(m_typed)
        else:
            # Fallback for legacy format
            checkpoint = {
                "v": 1,
                "id": model.checkpoint_id,
                "ts": raw_data.get("ts", model.created_at.isoformat()),
                "channel_values": raw_data.get("channel_values", {}),
                "channel_versions": raw_data.get("channel_versions", {}),
                "versions_seen": raw_data.get("versions_seen", {}),
            }
            metadata = {}

        parent_config = (
            {
                "configurable": {
                    "thread_id": model.thread_id,
                    "checkpoint_id": model.parent_checkpoint_id,
                }
            }
            if model.parent_checkpoint_id
            else None
        )

        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": model.thread_id,
                    "checkpoint_id": model.checkpoint_id,
                    "checkpoint_ns": config.get("configurable", {}).get("checkpoint_ns", ""),
                }
            },
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,  # type: ignore[arg-type]
            pending_writes=[],
        )

    async def aget_tuple(
        self,
        config: RunnableConfig,
    ) -> CheckpointTuple | None:
        """Get the checkpoint tuple for a thread asynchronously.

        Args:
            config: Configuration containing thread_id and optional checkpoint_id

        Returns:
            Optional[CheckpointTuple]: Retrieved checkpoint tuple or None
        """
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        if not thread_id:
            logger.warning("No thread_id provided in config")
            return None

        checkpoint_id = configurable.get("checkpoint_id")
        logger.info(
            "Retrieving checkpoint tuple",
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
        )

        try:
            stmt = select(CheckpointModel).where(CheckpointModel.thread_id == str(thread_id))
            if checkpoint_id:
                stmt = stmt.where(CheckpointModel.checkpoint_id == str(checkpoint_id))
            stmt = stmt.order_by(desc(CheckpointModel.created_at)).limit(1)

            result = await self.session.execute(stmt)
            model = result.scalars().first()

            if not model:
                logger.info(
                    "No checkpoint found",
                    thread_id=thread_id,
                    checkpoint_id=checkpoint_id,
                )
                return None

            return self._model_to_tuple(model, config)

        except Exception as e:
            logger.error(
                "Failed to retrieve checkpoint",
                error=str(e),
                thread_id=thread_id,
            )
            return None

    async def aget(
        self,
        config: RunnableConfig,
    ) -> Checkpoint | None:
        """Backward-compatible helper to get latest checkpoint.

        Args:
            config: Configuration containing thread_id

        Returns:
            Optional[Checkpoint]: Latest checkpoint or None
        """
        tuple_res = await self.aget_tuple(config)
        return tuple_res.checkpoint if tuple_res else None

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Save a checkpoint asynchronously with parameterized query.

        Args:
            config: Configuration containing thread_id
            checkpoint: Checkpoint to save
            metadata: Metadata associated with checkpoint
            new_versions: Channel version mappings

        Returns:
            RunnableConfig: Updated configuration containing checkpoint_id
        """
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        if not thread_id:
            logger.warning("No thread_id provided in config")
            return config

        checkpoint_id = checkpoint["id"]
        logger.info("Saving checkpoint", thread_id=thread_id, checkpoint_id=checkpoint_id)

        try:
            type_c, bytes_c = self.serde.dumps_typed(checkpoint)
            type_m, bytes_m = self.serde.dumps_typed(metadata)
            payload = {
                "checkpoint": {"type": type_c, "data": bytes_c.hex()},
                "metadata": {"type": type_m, "data": bytes_m.hex()},
            }

            parent_id = configurable.get("checkpoint_id")
            model = CheckpointModel(
                thread_id=str(thread_id),
                checkpoint_id=str(checkpoint_id),
                parent_checkpoint_id=str(parent_id) if parent_id else None,
                checkpoint_data=json.dumps(payload),
            )

            self.session.add(model)
            await self.session.commit()

            return {
                "configurable": {
                    **configurable,
                    "thread_id": str(thread_id),
                    "checkpoint_id": str(checkpoint_id),
                }
            }

        except Exception as e:
            logger.error(
                "Failed to save checkpoint",
                error=str(e),
                thread_id=thread_id,
            )
            await self.session.rollback()
            return config

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Store intermediate writes asynchronously (no-op for single step checkpoints)."""
        pass

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """List checkpoints for a thread asynchronously.

        Args:
            config: Optional configuration containing thread_id
            filter: Optional metadata filter
            before: Optional older config
            limit: Maximum checkpoints to return

        Yields:
            CheckpointTuple: Checkpoint tuples in descending order
        """
        if not config:
            return

        thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id:
            return

        stmt = select(CheckpointModel).where(CheckpointModel.thread_id == str(thread_id))
        stmt = stmt.order_by(desc(CheckpointModel.created_at)).limit(limit or 10)

        try:
            result = await self.session.execute(stmt)
            models = result.scalars().all()
            for model in models:
                yield self._model_to_tuple(model, config)
        except Exception as e:
            logger.error("Failed to list checkpoints", error=str(e), thread_id=thread_id)


async def get_checkpoint_saver(session: AsyncSession) -> PostgresCheckpointSaver:
    """Factory function to create checkpoint saver.

    Args:
        session: SQLAlchemy async session

    Returns:
        PostgresCheckpointSaver: Configured checkpoint saver
    """
    return PostgresCheckpointSaver(session)
