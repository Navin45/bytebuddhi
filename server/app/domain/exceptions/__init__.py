"""Domain exceptions for ByteBuddhi."""

from app.domain.exceptions.base import DomainException
from app.domain.exceptions.conversation_exceptions import (
    ConversationNotFoundException,
    InvalidMessageRoleException,
    MessageNotFoundException,
)
from app.domain.exceptions.project_exceptions import (
    ProjectAlreadyExistsException,
    ProjectIndexingException,
    ProjectNotFoundException,
)

__all__ = [
    "DomainException",
    "ProjectNotFoundException",
    "ProjectAlreadyExistsException",
    "ProjectIndexingException",
    "ConversationNotFoundException",
    "MessageNotFoundException",
    "InvalidMessageRoleException",
]
