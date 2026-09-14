"""OAuth login, callback, linking, and one-time token exchange routes."""

from html import escape
from urllib.parse import urlencode

from fastapi import APIRouter, Body, Depends, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.application.auth.oauth_service import OAuthService
from app.domain.exceptions.auth_exceptions import AuthenticationError
from app.domain.models.user import User
from app.domain.value_objects.identity_provider import (
    AuthFailureCategory,
    IdentityProvider,
    OAuthClientKind,
)
from app.infrastructure.auth import jwt_handler
from app.infrastructure.config.logger import get_logger
from app.interfaces.api.dependencies import get_oauth_service
from app.interfaces.api.middleware import get_current_user
from app.interfaces.api.schemas.auth_schema import TokenResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

_CLIENTS = {item.value: item for item in OAuthClientKind}
_PROVIDERS = {item.value: item for item in IdentityProvider}


class OauthExchangeRequest(BaseModel):
    code: str = Field(..., min_length=8, max_length=200)


class OauthLinkRequest(BaseModel):
    client: str = Field(default=OAuthClientKind.WEB.value, max_length=32)


class AuthProvidersResponse(BaseModel):
    google: bool
    github: bool


class OauthAuthorizationResponse(BaseModel):
    authorization_url: str


class LinkedIdentitiesResponse(BaseModel):
    providers: list[str]
    has_password: bool


def _parse_client(raw: str | None) -> OAuthClientKind:
    value = (raw or OAuthClientKind.WEB.value).strip().lower()
    client = _CLIENTS.get(value)
    if client is None:
        raise AuthenticationError(
            "Authentication failed",
            AuthFailureCategory.INVALID_REQUEST,
            http_status=400,
        )
    return client


def _parse_provider(raw: str) -> IdentityProvider:
    provider = _PROVIDERS.get(raw.strip().lower())
    if provider is None:
        raise AuthenticationError(
            "This sign-in method is not available",
            AuthFailureCategory.PROVIDER_DISABLED,
            http_status=404,
        )
    return provider


def _token_response(user: User) -> TokenResponse:
    access_token = jwt_handler.create_access_token(user.id)
    refresh_token = jwt_handler.create_refresh_token(user.id)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=jwt_handler.access_token_expire_minutes * 60,
    )


def _success_html(exchange_code: str) -> HTMLResponse:
    return HTMLResponse(
        content=(
            "<!DOCTYPE html><html><head><meta charset='utf-8'><title>ByteBuddhi signed in</title></head>"
            "<body><p>Sign-in complete. Return to ByteBuddhi and paste this one-time code. "
            "It expires shortly and can be used once.</p>"
            f"<p><code>{escape(exchange_code, quote=True)}</code></p></body></html>"
        )
    )


@router.get("/providers", response_model=AuthProvidersResponse)
async def list_auth_providers(oauth: OAuthService = Depends(get_oauth_service)) -> AuthProvidersResponse:
    enabled = oauth.enabled_providers()
    return AuthProvidersResponse(google=enabled["google"], github=enabled["github"])


@router.get("/{provider}/login")
async def oauth_login(
    provider: str,
    client: str | None = Query(default=None),
    next: str | None = Query(default=None),
    oauth: OAuthService = Depends(get_oauth_service),
):
    del next
    identity_provider = _parse_provider(provider)
    url = await oauth.start_login(identity_provider, _parse_client(client))
    logger.info("oauth_login_started", provider=identity_provider.value, result="redirect")
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    oauth: OAuthService = Depends(get_oauth_service),
):
    identity_provider = _parse_provider(provider)
    try:
        user, exchange, redirect = await oauth.complete_callback(
            identity_provider,
            code=code,
            state=state,
            error=error,
        )
    except AuthenticationError as exc:
        logger.info(
            "oauth_callback_failed",
            provider=identity_provider.value,
            result="failure",
            failure_category=exc.category.value,
        )
        raise
    logger.info("oauth_callback_succeeded", provider=identity_provider.value, result="success")
    del user
    if redirect:
        query = urlencode({"code": exchange})
        separator = "&" if "?" in redirect else "?"
        return RedirectResponse(url=f"{redirect}{separator}{query}", status_code=status.HTTP_302_FOUND)
    return _success_html(exchange)


@router.post("/oauth/exchange", response_model=TokenResponse)
async def oauth_exchange(
    request: OauthExchangeRequest,
    oauth: OAuthService = Depends(get_oauth_service),
) -> TokenResponse:
    user = await oauth.consume_exchange_code(request.code)
    logger.info("oauth_exchange_succeeded", result="success")
    return _token_response(user)


@router.post("/{provider}/link", response_model=OauthAuthorizationResponse)
async def oauth_link(
    provider: str,
    request: OauthLinkRequest = Body(default_factory=OauthLinkRequest),
    current_user: User = Depends(get_current_user),
    oauth: OAuthService = Depends(get_oauth_service),
) -> OauthAuthorizationResponse:
    identity_provider = _parse_provider(provider)
    client = _parse_client(request.client)
    url = await oauth.start_link(identity_provider, current_user, client)
    logger.info("oauth_link_started", provider=identity_provider.value, result="redirect")
    return OauthAuthorizationResponse(authorization_url=url)


@router.delete("/{provider}/link", status_code=status.HTTP_204_NO_CONTENT)
async def oauth_unlink(
    provider: str,
    current_user: User = Depends(get_current_user),
    oauth: OAuthService = Depends(get_oauth_service),
) -> None:
    identity_provider = _parse_provider(provider)
    await oauth.unlink(current_user, identity_provider)
    logger.info("oauth_unlinked", provider=identity_provider.value, result="success")


@router.get("/identities", response_model=LinkedIdentitiesResponse)
async def list_identities(
    current_user: User = Depends(get_current_user),
    oauth: OAuthService = Depends(get_oauth_service),
) -> LinkedIdentitiesResponse:
    providers = await oauth.list_linked_providers(current_user)
    return LinkedIdentitiesResponse(providers=providers, has_password=current_user.has_password())
