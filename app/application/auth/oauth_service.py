"""OAuth identity acquisition. Issues no provider tokens to clients."""

from __future__ import annotations

import hashlib
import re
from uuid import UUID

from app.application.auth.config import OAuthRuntimeConfig
from app.application.auth.identity_data import ExternalIdentityData
from app.application.auth.pkce import generate_pkce_pair, random_exchange_code, random_state
from app.application.auth.registry import OAuthProviderRegistry
from app.application.ports.output.auth.oauth_state_store import OAuthStateRecord, OAuthStateStore
from app.application.ports.output.observability.noop import NoOpTracer
from app.application.ports.output.observability.tracer import Tracer
from app.application.ports.output.repository.external_identity_repository import (
    ExternalIdentityRepository,
)
from app.application.ports.output.repository.user_repository import UserRepository
from app.domain.exceptions.auth_exceptions import AuthenticationError, DuplicateExternalIdentityError
from app.domain.models.external_identity import ExternalIdentity
from app.domain.models.observability import SpanAttributes, SpanNames
from app.domain.models.user import User
from app.domain.value_objects.identity_provider import (
    AuthFailureCategory,
    IdentityProvider,
    OAuthClientKind,
    OAuthFlow,
)

_USERNAME_SAFE = re.compile(r"[^a-z0-9_-]+")
_GENERIC_AUTH_FAILED = "Authentication failed"
_SIGNIN_EXPIRED = "Sign-in expired or is invalid. Try again."
_SIGNIN_UNAVAILABLE = "Sign-in is temporarily unavailable"
_SIGNIN_CANCELLED = "Sign-in was cancelled"
_SIGNIN_DISABLED = "This sign-in method is not available"
_LAST_CREDENTIAL = "Add another sign-in method before removing this one"
_ALREADY_LINKED = "This identity is already linked to an account"
_UNAUTHORIZED_LINK = "Sign in to link an account"


class OAuthService:
    """Map verified external identities onto the existing User model."""

    def __init__(
        self,
        *,
        registry: OAuthProviderRegistry,
        state_store: OAuthStateStore,
        users: UserRepository,
        identities: ExternalIdentityRepository,
        config: OAuthRuntimeConfig,
        tracer: Tracer | None = None,
    ) -> None:
        self._registry = registry
        self._state_store = state_store
        self._users = users
        self._identities = identities
        self._config = config
        self._tracer = tracer or NoOpTracer()

    def enabled_providers(self) -> dict[str, bool]:
        return {
            IdentityProvider.GOOGLE.value: self._is_enabled(IdentityProvider.GOOGLE),
            IdentityProvider.GITHUB.value: self._is_enabled(IdentityProvider.GITHUB),
        }

    async def start_login(self, provider: IdentityProvider, client: OAuthClientKind) -> str:
        return await self._start(provider, client, flow=OAuthFlow.LOGIN, user_id=None)

    async def start_link(self, provider: IdentityProvider, user: User, client: OAuthClientKind) -> str:
        if not user.is_active:
            raise AuthenticationError(_UNAUTHORIZED_LINK, AuthFailureCategory.UNAUTHORIZED, http_status=401)
        return await self._start(provider, client, flow=OAuthFlow.LINK, user_id=str(user.id))

    async def complete_callback(
        self,
        provider: IdentityProvider,
        *,
        code: str | None,
        state: str | None,
        error: str | None,
    ) -> tuple[User, str, str | None]:
        """Validate callback, map identity, issue a one-time exchange code.

        Returns (user, exchange_code, post_login_redirect).
        """
        with self._tracer.start_as_current_span(
            SpanNames.AUTH_OAUTH,
            attributes={
                SpanAttributes.AUTH_PROVIDER: provider.value,
                SpanAttributes.AUTH_FLOW: "callback",
            },
        ) as span:
            try:
                user, exchange, redirect = await self._complete_callback(provider, code=code, state=state, error=error)
                span.set_attribute(SpanAttributes.AUTH_RESULT, "success")
                return user, exchange, redirect
            except AuthenticationError as exc:
                span.set_attribute(SpanAttributes.AUTH_RESULT, "failure")
                span.set_attribute(SpanAttributes.AUTH_FAILURE_CATEGORY, exc.category.value)
                raise

    async def consume_exchange_code(self, code: str) -> User:
        if not code.strip():
            raise AuthenticationError(_GENERIC_AUTH_FAILED, AuthFailureCategory.INVALID_REQUEST, http_status=400)
        user_id = await self._state_store.consume_exchange(code.strip())
        if user_id is None:
            raise AuthenticationError(_SIGNIN_EXPIRED, AuthFailureCategory.STATE_INVALID, http_status=400)
        user = await self._users.get_by_id(UUID(user_id))
        if user is None or not user.is_active:
            raise AuthenticationError(_GENERIC_AUTH_FAILED, AuthFailureCategory.AUTHENTICATION_FAILED)
        return user

    async def unlink(self, user: User, provider: IdentityProvider) -> None:
        linked = await self._identities.list_by_user_id(user.id)
        remaining_oauth = [item for item in linked if item.provider != provider]
        if not remaining_oauth and not user.has_password():
            raise AuthenticationError(
                _LAST_CREDENTIAL,
                AuthFailureCategory.LAST_CREDENTIAL,
                http_status=400,
            )
        deleted = await self._identities.delete(user.id, provider)
        if not deleted:
            raise AuthenticationError(
                "This sign-in method is not linked",
                AuthFailureCategory.INVALID_REQUEST,
                http_status=400,
            )

    async def list_linked_providers(self, user: User) -> list[str]:
        linked = await self._identities.list_by_user_id(user.id)
        return [item.provider.value for item in linked]

    def _is_enabled(self, provider: IdentityProvider) -> bool:
        if provider is IdentityProvider.GOOGLE:
            flag = self._config.google_enabled
        elif provider is IdentityProvider.GITHUB:
            flag = self._config.github_enabled
        else:
            return False
        return flag and self._registry.is_registered(provider)

    def _redirect_uri(self, provider: IdentityProvider) -> str:
        if provider is IdentityProvider.GOOGLE:
            return self._config.google_redirect_uri
        return self._config.github_redirect_uri

    def _post_login_destination(self, client: OAuthClientKind) -> str | None:
        if client is OAuthClientKind.VSCODE:
            return self._config.vscode_redirect
        if client is OAuthClientKind.CLI:
            return self._config.cli_redirect
        return self._config.post_login_redirect

    async def _start(
        self,
        provider: IdentityProvider,
        client: OAuthClientKind,
        *,
        flow: OAuthFlow,
        user_id: str | None,
    ) -> str:
        if not self._is_enabled(provider):
            raise AuthenticationError(
                _SIGNIN_DISABLED,
                AuthFailureCategory.PROVIDER_DISABLED,
                http_status=503,
            )
        adapter = self._registry.get(provider)
        if adapter is None:
            raise AuthenticationError(
                _SIGNIN_DISABLED,
                AuthFailureCategory.CONFIGURATION_ERROR,
                http_status=503,
            )
        state = random_state()
        verifier, challenge = generate_pkce_pair()
        record = OAuthStateRecord(
            provider=provider,
            flow=flow,
            client=client,
            code_verifier=verifier,
            user_id=user_id,
        )
        await self._state_store.put_state(state, record, self._config.state_ttl_seconds)
        return adapter.build_authorization_url(
            state=state,
            code_challenge=challenge,
            redirect_uri=self._redirect_uri(provider),
        )

    async def _complete_callback(
        self,
        provider: IdentityProvider,
        *,
        code: str | None,
        state: str | None,
        error: str | None,
    ) -> tuple[User, str, str | None]:
        if error:
            category = (
                AuthFailureCategory.USER_DENIED
                if error in {"access_denied", "user_cancelled", "user_denied"}
                else AuthFailureCategory.AUTHENTICATION_FAILED
            )
            message = _SIGNIN_CANCELLED if category is AuthFailureCategory.USER_DENIED else _GENERIC_AUTH_FAILED
            status = 400 if category is AuthFailureCategory.USER_DENIED else 401
            raise AuthenticationError(message, category, http_status=status)
        if not state:
            raise AuthenticationError(_SIGNIN_EXPIRED, AuthFailureCategory.STATE_INVALID, http_status=400)
        if not code:
            raise AuthenticationError(_GENERIC_AUTH_FAILED, AuthFailureCategory.INVALID_REQUEST, http_status=400)
        if not self._is_enabled(provider):
            raise AuthenticationError(_SIGNIN_DISABLED, AuthFailureCategory.PROVIDER_DISABLED, http_status=503)

        record = await self._state_store.consume_state(state)
        if record is None:
            raise AuthenticationError(_SIGNIN_EXPIRED, AuthFailureCategory.STATE_INVALID, http_status=400)
        if record.provider != provider:
            raise AuthenticationError(_SIGNIN_EXPIRED, AuthFailureCategory.STATE_INVALID, http_status=400)

        adapter = self._registry.get(provider)
        if adapter is None:
            raise AuthenticationError(_SIGNIN_UNAVAILABLE, AuthFailureCategory.CONFIGURATION_ERROR, http_status=503)

        try:
            identity = await adapter.exchange_code(
                code=code,
                code_verifier=record.code_verifier,
                redirect_uri=self._redirect_uri(provider),
            )
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError(
                _SIGNIN_UNAVAILABLE,
                AuthFailureCategory.PROVIDER_UNAVAILABLE,
                http_status=503,
            ) from exc

        if identity.provider != provider or not identity.subject:
            raise AuthenticationError(
                _GENERIC_AUTH_FAILED,
                AuthFailureCategory.IDENTITY_VERIFICATION_FAILED,
            )

        user = await self._resolve_user(identity, record)
        if not user.is_active:
            raise AuthenticationError(_GENERIC_AUTH_FAILED, AuthFailureCategory.AUTHENTICATION_FAILED)

        exchange = random_exchange_code()
        await self._state_store.put_exchange(exchange, str(user.id), self._config.exchange_ttl_seconds)
        return user, exchange, self._post_login_destination(record.client)

    async def _resolve_user(self, identity: ExternalIdentityData, record: OAuthStateRecord) -> User:
        existing = await self._identities.get_by_provider_subject(identity.provider, identity.subject)
        if record.flow is OAuthFlow.LINK:
            return await self._link_to_authenticated_user(identity, record, existing)
        if existing is not None:
            user = await self._users.get_by_id(existing.user_id)
            if user is None:
                raise AuthenticationError(_GENERIC_AUTH_FAILED, AuthFailureCategory.AUTHENTICATION_FAILED)
            return user
        return await self._create_user(identity)

    async def _link_to_authenticated_user(
        self,
        identity: ExternalIdentityData,
        record: OAuthStateRecord,
        existing: ExternalIdentity | None,
    ) -> User:
        if not record.user_id:
            raise AuthenticationError(_UNAUTHORIZED_LINK, AuthFailureCategory.UNAUTHORIZED, http_status=401)
        user = await self._users.get_by_id(UUID(record.user_id))
        if user is None or not user.is_active:
            raise AuthenticationError(_UNAUTHORIZED_LINK, AuthFailureCategory.UNAUTHORIZED, http_status=401)
        if existing is not None:
            if existing.user_id != user.id:
                raise AuthenticationError(
                    _ALREADY_LINKED,
                    AuthFailureCategory.IDENTITY_ALREADY_LINKED,
                    http_status=409,
                )
            return user
        link = ExternalIdentity.create(
            user_id=user.id,
            provider=identity.provider,
            provider_subject=identity.subject,
            email_snapshot=identity.email,
            display_name_snapshot=identity.display_name,
            avatar_url_snapshot=identity.avatar_url,
        )
        try:
            await self._identities.create(link)
        except DuplicateExternalIdentityError:
            raced = await self._identities.get_by_provider_subject(identity.provider, identity.subject)
            if raced is None or raced.user_id != user.id:
                raise AuthenticationError(
                    _ALREADY_LINKED,
                    AuthFailureCategory.IDENTITY_ALREADY_LINKED,
                    http_status=409,
                ) from None
        return user

    async def _create_user(self, identity: ExternalIdentityData) -> User:
        email = await self._allocate_email(identity)
        username = await self._allocate_username(identity)
        user = User.create(email=email, username=username, password_hash=None)
        link = ExternalIdentity.create(
            user_id=user.id,
            provider=identity.provider,
            provider_subject=identity.subject,
            email_snapshot=identity.email,
            display_name_snapshot=identity.display_name,
            avatar_url_snapshot=identity.avatar_url,
        )
        try:
            await self._identities.create_with_user(user, link)
        except DuplicateExternalIdentityError:
            raced = await self._identities.get_by_provider_subject(identity.provider, identity.subject)
            if raced is None:
                raise AuthenticationError(_GENERIC_AUTH_FAILED, AuthFailureCategory.AUTHENTICATION_FAILED) from None
            found = await self._users.get_by_id(raced.user_id)
            if found is None:
                raise AuthenticationError(_GENERIC_AUTH_FAILED, AuthFailureCategory.AUTHENTICATION_FAILED) from None
            return found
        created = await self._users.get_by_id(user.id)
        return created or user

    async def _allocate_email(self, identity: ExternalIdentityData) -> str:
        candidate = (identity.email or "").strip().lower()
        if candidate and identity.email_verified:
            taken = await self._users.exists_by_email(candidate)
            if not taken:
                return candidate
        digest = hashlib.sha256(f"{identity.provider.value}:{identity.subject}".encode()).hexdigest()[:16]
        return f"oauth-{identity.provider.value}-{digest}@noreply.example"

    async def _allocate_username(self, identity: ExternalIdentityData) -> str:
        source = (identity.display_name or identity.email or identity.subject).split("@")[0]
        base = _USERNAME_SAFE.sub("-", source.lower()).strip("-_")[:40] or "user"
        candidate = base
        suffix = 0
        while await self._users.exists_by_username(candidate):
            suffix += 1
            candidate = f"{base}-{suffix}"
            if suffix > 50:
                digest = hashlib.sha256(identity.subject.encode()).hexdigest()[:10]
                candidate = f"{base}-{digest}"
                break
        return candidate
