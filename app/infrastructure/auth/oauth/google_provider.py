"""Google OpenID Connect identity provider adapter."""

from urllib.parse import urlencode

from app.application.auth.identity_data import ExternalIdentityData
from app.domain.exceptions.auth_exceptions import AuthenticationError
from app.domain.exceptions.connector_exceptions import (
    ConnectorAuthenticationError,
    ConnectorError,
    ConnectorTimeoutError,
)
from app.domain.value_objects.identity_provider import AuthFailureCategory, IdentityProvider
from app.infrastructure.auth.oauth.google_id_token import GoogleIdTokenVerifier, IdTokenVerifier
from app.infrastructure.http.external_client import ExternalHttpClient

_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPES = "openid email profile"
_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})


class GoogleOAuthProvider:
    """Authorization-code Google login. Does not persist Google tokens."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        http_client: ExternalHttpClient,
        verifier: IdTokenVerifier | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http_client
        self._verifier = verifier or GoogleIdTokenVerifier()
        self._timeout = timeout_seconds

    @property
    def provider(self) -> IdentityProvider:
        return IdentityProvider.GOOGLE

    def build_authorization_url(
        self,
        *,
        state: str,
        code_challenge: str,
        redirect_uri: str,
    ) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": _SCOPES,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{_AUTHORIZE_URL}?{query}"

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> ExternalIdentityData:
        try:
            response = await self._http.post(
                _TOKEN_URL,
                provider="google-oauth",
                headers={"Accept": "application/json"},
                data={
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
                timeout=self._timeout,
            )
        except ConnectorTimeoutError as exc:
            raise AuthenticationError(
                "Sign-in is temporarily unavailable",
                AuthFailureCategory.PROVIDER_UNAVAILABLE,
                http_status=503,
            ) from exc
        except ConnectorAuthenticationError as exc:
            raise AuthenticationError(
                "Authentication failed",
                AuthFailureCategory.CODE_EXCHANGE_FAILED,
            ) from exc
        except ConnectorError as exc:
            raise AuthenticationError(
                "Sign-in is temporarily unavailable",
                AuthFailureCategory.PROVIDER_UNAVAILABLE,
                http_status=503,
            ) from exc

        if not isinstance(response, dict):
            raise AuthenticationError(
                "Authentication failed",
                AuthFailureCategory.IDENTITY_VERIFICATION_FAILED,
            )
        id_token_value = response.get("id_token")
        if not isinstance(id_token_value, str) or not id_token_value:
            raise AuthenticationError(
                "Authentication failed",
                AuthFailureCategory.IDENTITY_VERIFICATION_FAILED,
            )
        try:
            claims = self._verifier.verify(id_token_value, audience=self._client_id)
        except Exception as exc:
            raise AuthenticationError(
                "Authentication failed",
                AuthFailureCategory.IDENTITY_VERIFICATION_FAILED,
            ) from exc
        return self._identity_from_claims(claims)

    def _identity_from_claims(self, claims: dict[str, object]) -> ExternalIdentityData:
        issuer = str(claims.get("iss") or "")
        if issuer not in _ISSUERS:
            raise AuthenticationError(
                "Authentication failed",
                AuthFailureCategory.IDENTITY_VERIFICATION_FAILED,
            )
        audience = claims.get("aud")
        if audience != self._client_id:
            raise AuthenticationError(
                "Authentication failed",
                AuthFailureCategory.IDENTITY_VERIFICATION_FAILED,
            )
        subject = str(claims.get("sub") or "").strip()
        if not subject:
            raise AuthenticationError(
                "Authentication failed",
                AuthFailureCategory.IDENTITY_VERIFICATION_FAILED,
            )
        email = claims.get("email")
        email_value = str(email).strip() if isinstance(email, str) and email.strip() else None
        verified_raw = claims.get("email_verified")
        email_verified = verified_raw is True or verified_raw == "true"
        name = claims.get("name")
        picture = claims.get("picture")
        return ExternalIdentityData(
            provider=IdentityProvider.GOOGLE,
            subject=subject,
            email=email_value,
            email_verified=email_verified,
            display_name=str(name) if isinstance(name, str) else None,
            avatar_url=str(picture) if isinstance(picture, str) else None,
        )
