"""Value objects package initialization."""

from app.domain.value_objects.email import Email
from app.domain.value_objects.file_path import FilePath
from app.domain.value_objects.identity_provider import (
    AuthFailureCategory,
    IdentityProvider,
    OAuthClientKind,
    OAuthFlow,
)
from app.domain.value_objects.language import Language, ProgrammingLanguage

__all__ = [
    "AuthFailureCategory",
    "Email",
    "FilePath",
    "IdentityProvider",
    "Language",
    "OAuthClientKind",
    "OAuthFlow",
    "ProgrammingLanguage",
]
