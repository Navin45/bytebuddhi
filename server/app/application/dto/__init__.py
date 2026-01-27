"""Data Transfer Objects package.

DTOs are used to transfer data between layers, particularly
from the API layer to the application layer and vice versa.
"""

from app.application.dto.chat_dto import (
    ConversationResponseDTO,
    CreateConversationDTO,
    MessageResponseDTO,
    SendMessageDTO,
)
from app.application.dto.project_dto import (
    CreateProjectDTO,
    ProjectResponseDTO,
    UpdateProjectDTO,
)

__all__ = [
    "CreateConversationDTO",
    "SendMessageDTO",
    "ConversationResponseDTO",
    "MessageResponseDTO",
    "CreateProjectDTO",
    "UpdateProjectDTO",
    "ProjectResponseDTO",
]
