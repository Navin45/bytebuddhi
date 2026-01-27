"""API schemas package initialization."""

from app.interfaces.api.schemas.auth_schema import (
    PasswordChangeRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from app.interfaces.api.schemas.chat_schema import (
    ChatRequest,
    ChatResponse,
    ConversationCreateRequest,
    ConversationResponse,
    ConversationUpdateRequest,
    MessageCreateRequest,
    MessageFeedbackRequest,
    MessageResponse,
    StreamChunk,
)
from app.interfaces.api.schemas.common import (
    BaseResponse,
    ErrorResponse,
    HealthResponse,
    IDResponse,
    PaginatedResponse,
    PaginationParams,
    TimestampMixin,
)
from app.interfaces.api.schemas.project_schema import (
    ProjectCreateRequest,
    ProjectIndexRequest,
    ProjectIndexResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)

__all__ = [
    # Common
    "BaseResponse",
    "ErrorResponse",
    "HealthResponse",
    "IDResponse",
    "PaginatedResponse",
    "PaginationParams",
    "TimestampMixin",
    # Auth
    "UserRegisterRequest",
    "UserLoginRequest",
    "TokenResponse",
    "RefreshTokenRequest",
    "UserResponse",
    "PasswordChangeRequest",
    "PasswordResetRequest",
    "PasswordResetConfirm",
    # Project
    "ProjectCreateRequest",
    "ProjectUpdateRequest",
    "ProjectResponse",
    "ProjectIndexRequest",
    "ProjectIndexResponse",
    # Chat
    "ConversationCreateRequest",
    "ConversationUpdateRequest",
    "ConversationResponse",
    "MessageCreateRequest",
    "MessageResponse",
    "MessageFeedbackRequest",
    "ChatRequest",
    "ChatResponse",
    "StreamChunk",
]
