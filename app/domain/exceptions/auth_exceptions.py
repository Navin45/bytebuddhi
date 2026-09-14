"""Authentication domain errors. Safe messages only; never include provider bodies."""

from app.domain.exceptions.base import DomainException
from app.domain.value_objects.identity_provider import AuthFailureCategory


class AuthenticationError(DomainException):
    """Controlled authentication failure with a normalized category."""

    def __init__(
        self,
        message: str,
        category: AuthFailureCategory,
        *,
        http_status: int = 401,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.http_status = http_status


class DuplicateExternalIdentityError(DomainException):
    """Raised when (provider, provider_subject) already exists."""

    def __init__(self) -> None:
        super().__init__("External identity already exists")
