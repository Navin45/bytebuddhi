"""OAuthService identity mapping, state, linking, and takeover protection."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.application.auth.config import OAuthRuntimeConfig
from app.application.auth.identity_data import ExternalIdentityData
from app.application.auth.oauth_service import OAuthService
from app.application.auth.registry import OAuthProviderRegistry
from app.application.ports.output.auth.oauth_state_store import OAuthStateRecord
from app.domain.exceptions.auth_exceptions import AuthenticationError, DuplicateExternalIdentityError
from app.domain.models.external_identity import ExternalIdentity
from app.domain.models.user import User
from app.domain.value_objects.identity_provider import (
    AuthFailureCategory,
    IdentityProvider,
    OAuthClientKind,
    OAuthFlow,
)
from app.infrastructure.auth.jwt_handler import JWTHandler
from app.infrastructure.auth.oauth.memory_state_store import MemoryOAuthStateStore


def _config(**overrides: object) -> OAuthRuntimeConfig:
    data: dict[str, object] = {
        "google_enabled": True,
        "github_enabled": True,
        "google_redirect_uri": "http://127.0.0.1:8000/api/v1/auth/google/callback",
        "github_redirect_uri": "http://127.0.0.1:8000/api/v1/auth/github/callback",
        "state_ttl_seconds": 600,
        "exchange_ttl_seconds": 120,
        "post_login_redirect": "https://app.example/signed-in",
        "vscode_redirect": "vscode://bytebuddhi.bytebuddhi/oauth",
        "cli_redirect": None,
    }
    data.update(overrides)
    return OAuthRuntimeConfig(**data)  # type: ignore[arg-type]


def _identity(
    provider: IdentityProvider = IdentityProvider.GOOGLE,
    subject: str = "google-sub-1",
    email: str | None = "oauth@example.com",
    verified: bool = True,
) -> ExternalIdentityData:
    return ExternalIdentityData(
        provider=provider,
        subject=subject,
        email=email,
        email_verified=verified,
        display_name="OAuth User",
        avatar_url=None,
    )


class FakeProvider:
    def __init__(self, identity: ExternalIdentityData, error: Exception | None = None) -> None:
        self._identity = identity
        self.error = error
        self.last_code: str | None = None

    @property
    def provider(self) -> IdentityProvider:
        return self._identity.provider

    def build_authorization_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str:
        return f"https://idp.example/authorize?state={state}"

    async def exchange_code(self, *, code: str, code_verifier: str, redirect_uri: str) -> ExternalIdentityData:
        self.last_code = code
        if self.error:
            raise self.error
        return self._identity


class FakeUsers:
    def __init__(self, users: list[User] | None = None) -> None:
        self.items = {user.id: user for user in users or []}

    async def create(self, user: User) -> User:
        self.items[user.id] = user
        return user

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self.items.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self.items.values() if u.email == email), None)

    async def get_by_username(self, username: str) -> User | None:
        return next((u for u in self.items.values() if u.username == username), None)

    async def update(self, user: User) -> User:
        self.items[user.id] = user
        return user

    async def delete(self, user_id: UUID) -> bool:
        return self.items.pop(user_id, None) is not None

    async def exists_by_email(self, email: str) -> bool:
        return any(u.email == email for u in self.items.values())

    async def exists_by_username(self, username: str) -> bool:
        return any(u.username == username for u in self.items.values())


class FakeIdentities:
    def __init__(self) -> None:
        self.items: list[ExternalIdentity] = []
        self.fail_create = False

    async def get_by_provider_subject(
        self, provider: IdentityProvider, provider_subject: str
    ) -> ExternalIdentity | None:
        return next(
            (item for item in self.items if item.provider == provider and item.provider_subject == provider_subject),
            None,
        )

    async def list_by_user_id(self, user_id: UUID) -> list[ExternalIdentity]:
        return [item for item in self.items if item.user_id == user_id]

    async def create_with_user(self, user: User, identity: ExternalIdentity) -> ExternalIdentity:
        if self.fail_create:
            raise DuplicateExternalIdentityError()
        existing = await self.get_by_provider_subject(identity.provider, identity.provider_subject)
        if existing:
            raise DuplicateExternalIdentityError()
        self.items.append(identity)
        return identity

    async def create(self, identity: ExternalIdentity) -> ExternalIdentity:
        existing = await self.get_by_provider_subject(identity.provider, identity.provider_subject)
        if existing:
            raise DuplicateExternalIdentityError()
        self.items.append(identity)
        return identity

    async def delete(self, user_id: UUID, provider: IdentityProvider) -> bool:
        before = len(self.items)
        self.items = [item for item in self.items if not (item.user_id == user_id and item.provider == provider)]
        return len(self.items) < before


def _service(
    identity: ExternalIdentityData | None = None,
    *,
    users: FakeUsers | None = None,
    identities: FakeIdentities | None = None,
    config: OAuthRuntimeConfig | None = None,
    error: Exception | None = None,
) -> tuple[OAuthService, FakeUsers, FakeIdentities, MemoryOAuthStateStore, FakeProvider]:
    data = identity or _identity()
    provider = FakeProvider(data, error=error)
    users = users or FakeUsers()
    identities = identities or FakeIdentities()
    store = MemoryOAuthStateStore()
    users_for_create = users

    async def _create_with_user(user: User, identity_row: ExternalIdentity) -> ExternalIdentity:
        users_for_create.items[user.id] = user
        return await FakeIdentities.create_with_user(identities, user, identity_row)

    identities.create_with_user = _create_with_user  # type: ignore[method-assign]
    service = OAuthService(
        registry=OAuthProviderRegistry({data.provider: provider}),
        state_store=store,
        users=users,
        identities=identities,
        config=config or _config(),
    )
    return service, users, identities, store, provider


@pytest.mark.asyncio
async def test_valid_google_login_creates_user_and_identity() -> None:
    service, _users, identities, _store, _provider = _service()
    url = await service.start_login(IdentityProvider.GOOGLE, OAuthClientKind.WEB)
    state = url.rsplit("state=", 1)[-1]
    user, exchange, redirect = await service.complete_callback(
        IdentityProvider.GOOGLE, code="ok-code", state=state, error=None
    )
    assert user.password_hash is None
    assert identities.items[0].provider_subject == "google-sub-1"
    assert identities.items[0].user_id == user.id
    assert redirect == "https://app.example/signed-in"
    consumed = await service.consume_exchange_code(exchange)
    assert consumed.id == user.id


@pytest.mark.asyncio
async def test_valid_github_login_uses_numeric_subject() -> None:
    identity = _identity(IdentityProvider.GITHUB, "998877", "gh@example.com")
    service, _users, identities, _store, _provider = _service(identity)
    url = await service.start_login(IdentityProvider.GITHUB, OAuthClientKind.CLI)
    state = url.rsplit("state=", 1)[-1]
    user, _exchange, redirect = await service.complete_callback(
        IdentityProvider.GITHUB, code="gh-code", state=state, error=None
    )
    assert identities.items[0].provider_subject == "998877"
    assert user.id == identities.items[0].user_id
    assert redirect is None


@pytest.mark.asyncio
async def test_missing_and_wrong_state_rejected() -> None:
    service, *_rest = _service()
    with pytest.raises(AuthenticationError) as missing:
        await service.complete_callback(IdentityProvider.GOOGLE, code="x", state=None, error=None)
    assert missing.value.category is AuthFailureCategory.STATE_INVALID
    with pytest.raises(AuthenticationError) as wrong:
        await service.complete_callback(IdentityProvider.GOOGLE, code="x", state="forged", error=None)
    assert wrong.value.category is AuthFailureCategory.STATE_INVALID


@pytest.mark.asyncio
async def test_state_replay_rejected() -> None:
    service, *_rest = _service()
    url = await service.start_login(IdentityProvider.GOOGLE, OAuthClientKind.WEB)
    state = url.rsplit("state=", 1)[-1]
    await service.complete_callback(IdentityProvider.GOOGLE, code="ok", state=state, error=None)
    with pytest.raises(AuthenticationError) as replay:
        await service.complete_callback(IdentityProvider.GOOGLE, code="ok", state=state, error=None)
    assert replay.value.category is AuthFailureCategory.STATE_INVALID


@pytest.mark.asyncio
async def test_expired_state_rejected() -> None:
    service, _users, _identities, store, _provider = _service()
    url = await service.start_login(IdentityProvider.GOOGLE, OAuthClientKind.WEB)
    state = url.rsplit("state=", 1)[-1]
    record = store._states[state][1]
    store._states[state] = (0.0, record)
    with pytest.raises(AuthenticationError) as expired:
        await service.complete_callback(IdentityProvider.GOOGLE, code="ok", state=state, error=None)
    assert expired.value.category is AuthFailureCategory.STATE_INVALID


@pytest.mark.asyncio
async def test_missing_code_and_user_denied() -> None:
    service, *_rest = _service()
    url = await service.start_login(IdentityProvider.GOOGLE, OAuthClientKind.WEB)
    state = url.rsplit("state=", 1)[-1]
    with pytest.raises(AuthenticationError) as missing:
        await service.complete_callback(IdentityProvider.GOOGLE, code=None, state=state, error=None)
    assert missing.value.category is AuthFailureCategory.INVALID_REQUEST
    with pytest.raises(AuthenticationError) as denied:
        await service.complete_callback(IdentityProvider.GOOGLE, code="x", state="ignored", error="access_denied")
    assert denied.value.category is AuthFailureCategory.USER_DENIED


@pytest.mark.asyncio
async def test_invalid_code_and_provider_timeout() -> None:
    failed = _service(error=AuthenticationError("Authentication failed", AuthFailureCategory.CODE_EXCHANGE_FAILED))
    url = await failed[0].start_login(IdentityProvider.GOOGLE, OAuthClientKind.WEB)
    state = url.rsplit("state=", 1)[-1]
    with pytest.raises(AuthenticationError) as invalid:
        await failed[0].complete_callback(IdentityProvider.GOOGLE, code="bad", state=state, error=None)
    assert invalid.value.category is AuthFailureCategory.CODE_EXCHANGE_FAILED

    timed = _service(error=TimeoutError("hang"))
    url = await timed[0].start_login(IdentityProvider.GOOGLE, OAuthClientKind.WEB)
    state = url.rsplit("state=", 1)[-1]
    with pytest.raises(AuthenticationError) as unavailable:
        await timed[0].complete_callback(IdentityProvider.GOOGLE, code="x", state=state, error=None)
    assert unavailable.value.category is AuthFailureCategory.PROVIDER_UNAVAILABLE


@pytest.mark.asyncio
async def test_email_collision_does_not_take_over_local_account() -> None:
    local = User.create(email="alice@example.com", username="alice", password_hash="hashed")
    users = FakeUsers([local])
    service, _users, identities, _store, _provider = _service(_identity(email="alice@example.com"), users=users)
    url = await service.start_login(IdentityProvider.GOOGLE, OAuthClientKind.WEB)
    state = url.rsplit("state=", 1)[-1]
    oauth_user, _exchange, _redirect = await service.complete_callback(
        IdentityProvider.GOOGLE, code="ok", state=state, error=None
    )
    assert oauth_user.id != local.id
    assert oauth_user.email != "alice@example.com"
    assert identities.items[0].user_id == oauth_user.id


@pytest.mark.asyncio
async def test_explicit_link_attaches_to_authenticated_user() -> None:
    local = User.create(email="alice@example.com", username="alice", password_hash="hashed")
    users = FakeUsers([local])
    service, _users, identities, _store, _provider = _service(_identity(email="alice@example.com"), users=users)
    url = await service.start_link(IdentityProvider.GOOGLE, local, OAuthClientKind.WEB)
    state = url.rsplit("state=", 1)[-1]
    user, _exchange, _redirect = await service.complete_callback(
        IdentityProvider.GOOGLE, code="ok", state=state, error=None
    )
    assert user.id == local.id
    assert identities.items[0].user_id == local.id


@pytest.mark.asyncio
async def test_unauthorized_link_without_session_rejected() -> None:
    service, _users, identities, store, _provider = _service()
    record = OAuthStateRecord(
        provider=IdentityProvider.GOOGLE,
        flow=OAuthFlow.LINK,
        client=OAuthClientKind.WEB,
        code_verifier="verifier",
        user_id=None,
    )
    await store.put_state("link-state", record, 600)
    with pytest.raises(AuthenticationError) as exc:
        await service.complete_callback(IdentityProvider.GOOGLE, code="ok", state="link-state", error=None)
    assert exc.value.category is AuthFailureCategory.UNAUTHORIZED
    assert identities.items == []


@pytest.mark.asyncio
async def test_unlink_last_credential_rejected() -> None:
    service, _users, identities, _store, _provider = _service()
    url = await service.start_login(IdentityProvider.GOOGLE, OAuthClientKind.WEB)
    state = url.rsplit("state=", 1)[-1]
    user, _exchange, _redirect = await service.complete_callback(
        IdentityProvider.GOOGLE, code="ok", state=state, error=None
    )
    with pytest.raises(AuthenticationError) as exc:
        await service.unlink(user, IdentityProvider.GOOGLE)
    assert exc.value.category is AuthFailureCategory.LAST_CREDENTIAL
    user.update_password("new-hash")
    await service.unlink(user, IdentityProvider.GOOGLE)
    assert identities.items == []


@pytest.mark.asyncio
async def test_duplicate_provider_identity_returns_same_user() -> None:
    service, _users, identities, _store, _provider = _service()
    url = await service.start_login(IdentityProvider.GOOGLE, OAuthClientKind.WEB)
    state = url.rsplit("state=", 1)[-1]
    first, _e1, _r1 = await service.complete_callback(IdentityProvider.GOOGLE, code="ok", state=state, error=None)
    url = await service.start_login(IdentityProvider.GOOGLE, OAuthClientKind.WEB)
    state = url.rsplit("state=", 1)[-1]
    second, _e2, _r2 = await service.complete_callback(IdentityProvider.GOOGLE, code="ok", state=state, error=None)
    assert first.id == second.id
    assert len(identities.items) == 1


@pytest.mark.asyncio
async def test_oauth_jwt_subject_is_user_id() -> None:
    service, *_rest = _service()
    url = await service.start_login(IdentityProvider.GOOGLE, OAuthClientKind.WEB)
    state = url.rsplit("state=", 1)[-1]
    user, _exchange, _redirect = await service.complete_callback(
        IdentityProvider.GOOGLE, code="ok", state=state, error=None
    )
    handler = JWTHandler(secret_key="unit-test-secret-key-32-chars-min", algorithm="HS256")
    token = handler.create_access_token(user.id, additional_claims={"sub": "google-sub-1", "type": "forged"})
    assert handler.verify_token(token) == user.id


@pytest.mark.asyncio
async def test_disabled_provider_does_not_affect_the_other() -> None:
    identity = _identity(IdentityProvider.GITHUB, "1", "gh@example.com")
    service, *_rest = _service(identity, config=_config(google_enabled=False, github_enabled=True))
    with pytest.raises(AuthenticationError) as google:
        await service.start_login(IdentityProvider.GOOGLE, OAuthClientKind.WEB)
    assert google.value.category is AuthFailureCategory.PROVIDER_DISABLED
    url = await service.start_login(IdentityProvider.GITHUB, OAuthClientKind.WEB)
    assert "authorize" in url


@pytest.mark.asyncio
async def test_exchange_code_is_single_use() -> None:
    service, *_rest = _service()
    url = await service.start_login(IdentityProvider.GOOGLE, OAuthClientKind.WEB)
    state = url.rsplit("state=", 1)[-1]
    _user, exchange, _redirect = await service.complete_callback(
        IdentityProvider.GOOGLE, code="ok", state=state, error=None
    )
    await service.consume_exchange_code(exchange)
    with pytest.raises(AuthenticationError):
        await service.consume_exchange_code(exchange)


@pytest.mark.asyncio
async def test_unverified_email_is_not_used_as_login_identifier() -> None:
    service, _users, _identities, _store, _provider = _service(
        _identity(email="unverified@example.com", verified=False)
    )
    url = await service.start_login(IdentityProvider.GOOGLE, OAuthClientKind.WEB)
    state = url.rsplit("state=", 1)[-1]
    user, _exchange, _redirect = await service.complete_callback(
        IdentityProvider.GOOGLE, code="ok", state=state, error=None
    )
    assert user.email != "unverified@example.com"
    assert user.email.endswith("@noreply.example")
