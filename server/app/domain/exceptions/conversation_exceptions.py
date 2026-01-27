from app.domain.exceptions.base import DomainException


class ConversationNotFoundException(DomainException):
    """Raised when a conversation is not found."""

    def __init__(self, conversation_id: str):
        super().__init__(f"Conversation with id {conversation_id} not found")


class MessageNotFoundException(DomainException):
    """Raised when a message is not found."""

    def __init__(self, message_id: str):
        super().__init__(f"Message with id {message_id} not found")


class InvalidMessageRoleException(DomainException):
    """Raised when an invalid message role is provided."""

    def __init__(self, role: str):
        super().__init__(f"Invalid message role: {role}")