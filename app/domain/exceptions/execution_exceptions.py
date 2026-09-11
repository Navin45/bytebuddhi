from app.domain.exceptions.base import DomainException


class ExecutionContextRequired(DomainException):
    """Raised when a canonical execution path is invoked without trusted ExecutionContext."""

    def __init__(self, message: str = "Trusted ExecutionContext is required"):
        super().__init__(message)
