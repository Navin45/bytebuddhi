"""PostgreSQL checkpoint saver for LangGraph.

This module implements a checkpoint saver that stores LangGraph agent
state in PostgreSQL, enabling conversation persistence and resumption.
"""

import json
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint
from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

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

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    thread_id = Column(String(255), nullable=False, index=True)
    checkpoint_id = Column(String(255), nullable=False, unique=True)
    parent_checkpoint_id = Column(String(255), nullable=True)
    checkpoint_data = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PostgresCheckpointSaver(BaseCheckpointSaver):
    """PostgreSQL-based checkpoint saver for LangGraph.
    
    This class implements the BaseCheckpointSaver interface to store
    and retrieve agent checkpoints from PostgreSQL. It enables:
    - Conversation persistence across sessions
    - State recovery after errors
    - Conversation branching and replay
    
    Attributes:
        session: SQLAlchemy async session
    """

    def __init__(self, session: AsyncSession):
        """Initialize checkpoint saver with database session.
        
        Args:
            session: SQLAlchemy async session for database operations
        """
        super().__init__()
        self.session = session

    async def aget(
        self,
        config: Dict[str, Any],
    ) -> Optional[Checkpoint]:
        """Get the latest checkpoint for a thread.
        
        Retrieves the most recent checkpoint for the specified thread,
        enabling conversation resumption.
        
        Args:
            config: Configuration containing thread_id
            
        Returns:
            Optional[Checkpoint]: Latest checkpoint or None if not found
        """
        thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id:
            logger.warning("No thread_id provided in config")
            return None

        logger.info("Retrieving checkpoint", thread_id=thread_id)

        try:
            # Query for latest checkpoint
            result = await self.session.execute(
                f"""
                SELECT checkpoint_data, checkpoint_id, parent_checkpoint_id
                FROM agent_checkpoints
                WHERE thread_id = '{thread_id}'
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            row = result.fetchone()

            if not row:
                logger.info("No checkpoint found", thread_id=thread_id)
                return None

            # Deserialize checkpoint
            checkpoint_data = json.loads(row[0])
            checkpoint = Checkpoint(
                v=1,
                id=row[1],
                ts=checkpoint_data.get("ts"),
                channel_values=checkpoint_data.get("channel_values", {}),
                channel_versions=checkpoint_data.get("channel_versions", {}),
                versions_seen=checkpoint_data.get("versions_seen", {}),
            )

            logger.info("Checkpoint retrieved", thread_id=thread_id, checkpoint_id=row[1])
            return checkpoint

        except Exception as e:
            logger.error("Failed to retrieve checkpoint", error=str(e), thread_id=thread_id)
            return None

    async def aput(
        self,
        config: Dict[str, Any],
        checkpoint: Checkpoint,
    ) -> Dict[str, Any]:
        """Save a checkpoint to the database.
        
        Stores the current agent state as a checkpoint, enabling
        future resumption and replay.
        
        Args:
            config: Configuration containing thread_id
            checkpoint: Checkpoint to save
            
        Returns:
            Dict[str, Any]: Updated config with checkpoint metadata
        """
        thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id:
            logger.warning("No thread_id provided in config")
            return config

        logger.info("Saving checkpoint", thread_id=thread_id)

        try:
            # Serialize checkpoint
            checkpoint_data = {
                "ts": checkpoint.ts,
                "channel_values": checkpoint.channel_values,
                "channel_versions": checkpoint.channel_versions,
                "versions_seen": checkpoint.versions_seen,
            }

            # Create checkpoint record
            checkpoint_model = CheckpointModel(
                thread_id=thread_id,
                checkpoint_id=checkpoint.id,
                parent_checkpoint_id=checkpoint.parent_config.get("configurable", {}).get("checkpoint_id")
                if checkpoint.parent_config
                else None,
                checkpoint_data=json.dumps(checkpoint_data),
            )

            self.session.add(checkpoint_model)
            await self.session.commit()

            logger.info("Checkpoint saved", thread_id=thread_id, checkpoint_id=checkpoint.id)

            # Return updated config
            return {
                **config,
                "configurable": {
                    **config.get("configurable", {}),
                    "checkpoint_id": checkpoint.id,
                },
            }

        except Exception as e:
            logger.error("Failed to save checkpoint", error=str(e), thread_id=thread_id)
            await self.session.rollback()
            return config

    async def alist(
        self,
        config: Dict[str, Any],
        limit: int = 10,
    ) -> list[Checkpoint]:
        """List checkpoints for a thread.
        
        Retrieves multiple checkpoints for a thread, useful for
        viewing conversation history or debugging.
        
        Args:
            config: Configuration containing thread_id
            limit: Maximum number of checkpoints to return
            
        Returns:
            list[Checkpoint]: List of checkpoints, newest first
        """
        thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id:
            logger.warning("No thread_id provided in config")
            return []

        logger.info("Listing checkpoints", thread_id=thread_id, limit=limit)

        try:
            # Query for checkpoints
            result = await self.session.execute(
                f"""
                SELECT checkpoint_data, checkpoint_id, parent_checkpoint_id
                FROM agent_checkpoints
                WHERE thread_id = '{thread_id}'
                ORDER BY created_at DESC
                LIMIT {limit}
                """
            )
            rows = result.fetchall()

            # Deserialize checkpoints
            checkpoints = []
            for row in rows:
                checkpoint_data = json.loads(row[0])
                checkpoint = Checkpoint(
                    v=1,
                    id=row[1],
                    ts=checkpoint_data.get("ts"),
                    channel_values=checkpoint_data.get("channel_values", {}),
                    channel_versions=checkpoint_data.get("channel_versions", {}),
                    versions_seen=checkpoint_data.get("versions_seen", {}),
                )
                checkpoints.append(checkpoint)

            logger.info("Checkpoints listed", thread_id=thread_id, count=len(checkpoints))
            return checkpoints

        except Exception as e:
            logger.error("Failed to list checkpoints", error=str(e), thread_id=thread_id)
            return []


async def get_checkpoint_saver(session: AsyncSession) -> PostgresCheckpointSaver:
    """Factory function to create checkpoint saver.
    
    Args:
        session: SQLAlchemy async session
        
    Returns:
        PostgresCheckpointSaver: Configured checkpoint saver
    """
    return PostgresCheckpointSaver(session)
