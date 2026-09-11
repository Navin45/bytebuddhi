"""Domain exceptions for ByteBuddhi."""

from app.domain.exceptions.base import DomainException
from app.domain.exceptions.conversation_exceptions import (
    ConversationNotFoundException,
    InvalidMessageRoleException,
    MessageNotFoundException,
)
from app.domain.exceptions.execution_exceptions import ExecutionContextRequired
from app.domain.exceptions.project_exceptions import (
    ProjectAlreadyExistsException,
    ProjectIndexingException,
    ProjectNotFoundException,
)
from app.domain.exceptions.web_exceptions import (
    ContentTooLarge,
    FetchFailed,
    FetchTimeout,
    InvalidResearchRequest,
    PrivateAddressBlocked,
    RenderFailed,
    RenderTimeout,
    ResearchBudgetExceeded,
    ResearchCancelled,
    SearchFailed,
    UnsafeUrl,
    UnsupportedContentType,
    WebResearchError,
)

__all__ = [
    "ContentTooLarge",
    "ConversationNotFoundException",
    "DomainException",
    "ExecutionContextRequired",
    "FetchFailed",
    "FetchTimeout",
    "InvalidMessageRoleException",
    "InvalidResearchRequest",
    "MessageNotFoundException",
    "PrivateAddressBlocked",
    "ProjectAlreadyExistsException",
    "ProjectIndexingException",
    "ProjectNotFoundException",
    "RenderFailed",
    "RenderTimeout",
    "ResearchBudgetExceeded",
    "ResearchCancelled",
    "SearchFailed",
    "UnsafeUrl",
    "UnsupportedContentType",
    "WebResearchError",
]
