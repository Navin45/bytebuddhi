"""User domain model."""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4


class User:
    """Domain model for User entity.
    
    Represents a user in the ByteBuddhi system with authentication,
    quota management, and API access capabilities.
    """

    def __init__(
        self,
        id: UUID,
        email: str,
        username: str,
        password_hash: str,
        created_at: datetime,
        updated_at: datetime,
        is_active: bool = True,
        api_key: Optional[str] = None,
        usage_quota: int = 1000,
    ):
        """Initialize User entity.
        
        Args:
            id: Unique user identifier
            email: User email address
            username: Unique username
            password_hash: Hashed password
            created_at: Account creation timestamp
            updated_at: Last update timestamp
            is_active: Whether account is active
            api_key: Optional API key for programmatic access
            usage_quota: Monthly usage quota limit
        """
        self.id = id
        self.email = email
        self.username = username
        self.password_hash = password_hash
        self.created_at = created_at
        self.updated_at = updated_at
        self.is_active = is_active
        self.api_key = api_key
        self.usage_quota = usage_quota

    @staticmethod
    def create(
        email: str,
        username: str,
        password_hash: str,
        api_key: Optional[str] = None,
    ) -> "User":
        """Factory method to create a new user.
        
        Args:
            email: User email address
            username: Unique username
            password_hash: Hashed password
            api_key: Optional API key
            
        Returns:
            User: New user instance
        """
        now = datetime.utcnow()
        return User(
            id=uuid4(),
            email=email,
            username=username,
            password_hash=password_hash,
            created_at=now,
            updated_at=now,
            is_active=True,
            api_key=api_key,
            usage_quota=1000,
        )

    def deactivate(self) -> None:
        """Deactivate the user account."""
        self.is_active = False
        self.updated_at = datetime.utcnow()

    def activate(self) -> None:
        """Activate the user account."""
        self.is_active = True
        self.updated_at = datetime.utcnow()

    def update_quota(self, new_quota: int) -> None:
        """Update the user's usage quota.
        
        Args:
            new_quota: New quota limit
        """
        self.usage_quota = new_quota
        self.updated_at = datetime.utcnow()

    def update_api_key(self, new_api_key: str) -> None:
        """Update the user's API key.
        
        Args:
            new_api_key: New API key
        """
        self.api_key = new_api_key
        self.updated_at = datetime.utcnow()