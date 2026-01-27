"""User repository implementation."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.output.repository.user_repository import UserRepository
from app.domain.models.user import User
from app.infrastructure.persistence.postgres.models import UserModel


class UserRepositoryImpl(UserRepository):
    """PostgreSQL implementation of UserRepository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user: User) -> User:
        """Create a new user."""
        user_model = UserModel(
            id=user.id,
            email=user.email,
            username=user.username,
            password_hash=user.password_hash,
            created_at=user.created_at,
            updated_at=user.updated_at,
            is_active=user.is_active,
            api_key=user.api_key,
            usage_quota=user.usage_quota,
        )
        self.session.add(user_model)
        await self.session.flush()
        return self._to_domain(user_model)

    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        """Get user by ID."""
        result = await self.session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        user_model = result.scalar_one_or_none()
        return self._to_domain(user_model) if user_model else None

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        result = await self.session.execute(
            select(UserModel).where(UserModel.email == email)
        )
        user_model = result.scalar_one_or_none()
        return self._to_domain(user_model) if user_model else None

    async def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        result = await self.session.execute(
            select(UserModel).where(UserModel.username == username)
        )
        user_model = result.scalar_one_or_none()
        return self._to_domain(user_model) if user_model else None

    async def update(self, user: User) -> User:
        """Update user."""
        result = await self.session.execute(
            select(UserModel).where(UserModel.id == user.id)
        )
        user_model = result.scalar_one()
        
        user_model.email = user.email
        user_model.username = user.username
        user_model.password_hash = user.password_hash
        user_model.updated_at = user.updated_at
        user_model.is_active = user.is_active
        user_model.api_key = user.api_key
        user_model.usage_quota = user.usage_quota
        
        await self.session.flush()
        return self._to_domain(user_model)

    async def delete(self, user_id: UUID) -> bool:
        """Delete user."""
        result = await self.session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        user_model = result.scalar_one_or_none()
        if user_model:
            await self.session.delete(user_model)
            await self.session.flush()
            return True
        return False

    async def exists_by_email(self, email: str) -> bool:
        """Check if user exists by email."""
        result = await self.session.execute(
            select(UserModel.id).where(UserModel.email == email)
        )
        return result.scalar_one_or_none() is not None

    async def exists_by_username(self, username: str) -> bool:
        """Check if user exists by username."""
        result = await self.session.execute(
            select(UserModel.id).where(UserModel.username == username)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    def _to_domain(model: UserModel) -> User:
        """Convert SQLAlchemy model to domain model."""
        return User(
            id=model.id,
            email=model.email,
            username=model.username,
            password_hash=model.password_hash,
            created_at=model.created_at,
            updated_at=model.updated_at,
            is_active=model.is_active,
            api_key=model.api_key,
            usage_quota=model.usage_quota,
        )
