from app.domain.exceptions.base import DomainException


class ProjectNotFoundException(DomainException):
    """Raised when a project is not found."""

    def __init__(self, project_id: str):
        super().__init__(f"Project with id {project_id} not found")


class ProjectAlreadyExistsException(DomainException):
    """Raised when trying to create a project that already exists."""

    def __init__(self, project_name: str):
        super().__init__(f"Project with name {project_name} already exists")


class ProjectIndexingException(DomainException):
    """Raised when project indexing fails."""

    def __init__(self, message: str):
        super().__init__(f"Project indexing failed: {message}")


class ProjectOwnershipException(DomainException):
    """Raised when an operation attempts to access a project not owned by the user."""

    def __init__(self, project_id: str, user_id: str):
        super().__init__(f"User {user_id} is not authorized for project {project_id}")
