"""PostgreSQL implementation of ExternalIdentityRepository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.output.repository.external_identity_repository import (
    ExternalIdentityRepository,
)
from app.domain.exceptions.auth_exceptions import DuplicateExternalIdentityError
from app.domain.models.external_identity import ExternalIdentity
from app.domain.models.user import User
from app.domain.value_objects.identity_provider import IdentityProvider
from app.infrastructure.persistence.postgres.models import ExternalIdentityModel, UserModel


class ExternalIdentityRepositoryImpl(ExternalIdentityRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_provider_subject(
        self,
        provider: IdentityProvider,
        provider_subject: str,
    ) -> ExternalIdentity | None:
        result = await self.session.execute(
            select(ExternalIdentityModel).where(
                ExternalIdentityModel.provider == provider.value,
                ExternalIdentityModel.provider_subject == provider_subject,
            )
        )
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model else None

    async def list_by_user_id(self, user_id: UUID) -> list[ExternalIdentity]:
        result = await self.session.execute(
            select(ExternalIdentityModel).where(ExternalIdentityModel.user_id == user_id)
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    async def create_with_user(self, user: User, identity: ExternalIdentity) -> ExternalIdentity:
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
        identity_model = self._to_model(identity)
        self.session.add(user_model)
        self.session.add(identity_model)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise DuplicateExternalIdentityError() from exc
        return self._to_domain(identity_model)

    async def create(self, identity: ExternalIdentity) -> ExternalIdentity:
        model = self._to_model(identity)
        self.session.add(model)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise DuplicateExternalIdentityError() from exc
        return self._to_domain(model)

    async def delete(self, user_id: UUID, provider: IdentityProvider) -> bool:
        result = await self.session.execute(
            select(ExternalIdentityModel).where(
                ExternalIdentityModel.user_id == user_id,
                ExternalIdentityModel.provider == provider.value,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return False
        await self.session.delete(model)
        await self.session.flush()
        return True

    @staticmethod
    def _to_model(identity: ExternalIdentity) -> ExternalIdentityModel:
        return ExternalIdentityModel(
            id=identity.id,
            user_id=identity.user_id,
            provider=identity.provider.value,
            provider_subject=identity.provider_subject,
            email_snapshot=identity.email_snapshot,
            display_name_snapshot=identity.display_name_snapshot,
            avatar_url_snapshot=identity.avatar_url_snapshot,
            created_at=identity.created_at,
            updated_at=identity.updated_at,
        )

    @staticmethod
    def _to_domain(model: ExternalIdentityModel) -> ExternalIdentity:
        return ExternalIdentity(
            id=model.id,
            user_id=model.user_id,
            provider=IdentityProvider(model.provider),
            provider_subject=model.provider_subject,
            email_snapshot=model.email_snapshot,
            display_name_snapshot=model.display_name_snapshot,
            avatar_url_snapshot=model.avatar_url_snapshot,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
