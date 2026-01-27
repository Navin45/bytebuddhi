from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4


class Message:
    """Domain model for Message entity."""

    def __init__(
        self,
        id: UUID,
        conversation_id: UUID,
        role: str,
        content: str,
        created_at: datetime,
        metadata: Optional[dict] = None,
        parent_message_id: Optional[UUID] = None,
        feedback: Optional[int] = None,
    ):
        self.id = id
        self.conversation_id = conversation_id
        self.role = role
        self.content = content
        self.created_at = created_at
        self.metadata = metadata or {}
        self.parent_message_id = parent_message_id
        self.feedback = feedback

        # Validate role
        if role not in ["user", "assistant", "system", "tool"]:
            raise ValueError(f"Invalid role: {role}")

    @staticmethod
    def create(
        conversation_id: UUID,
        role: str,
        content: str,
        parent_message_id: Optional[UUID] = None,
        metadata: Optional[dict] = None,
    ) -> "Message":
        """Factory method to create a new message."""
        return Message(
            id=uuid4(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=datetime.utcnow(),
            metadata=metadata,
            parent_message_id=parent_message_id,
        )

    def add_feedback(self, feedback: int) -> None:
        """Add user feedback to the message."""
        if feedback not in [-1, 1]:
            raise ValueError("Feedback must be -1 or 1")
        self.feedback = feedback