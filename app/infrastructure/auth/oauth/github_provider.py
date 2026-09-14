"""GitHub OAuth identity provider adapter. Login only — not repository access."""

from urllib.parse import urlencode

from app.application.auth.identity_data import ExternalIdentityData
from app.domain.exceptions.auth_exceptions import AuthenticationError
from app.domain.exceptions.connector_exceptions import (
    ConnectorAuthenticationError,
    ConnectorError,
    ConnectorTimeoutError,
)
from app.domain.value_objects.identity_provider import AuthFailureCategory, IdentityProvider
from app.infrastructure.http.external_client import ExternalHttpClient

_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_USER_URL = "https://api.github.com/user"
_EMAILS_URL = "https://api.github.com/user/emails"
_SCOPES = "read:user user:email"
_FORBIDDEN_SCOPES = frozenset({"repo", "workflow", "admin:org", "delete_repo"})


class GitHubOAuthProvider:
    """Authorization-code GitHub login. Uses numeric account id as subject."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        http_client: ExternalHttpClient,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http_client
        self._timeout = timeout_seconds
        if any(scope in _FORBIDDEN_SCOPES for scope in _SCOPES.split()):
            raise RuntimeError("GitHub login must not request repository or org admin scopes")

    @property
    def provider(self) -> IdentityProvider:
        return IdentityProvider.GITHUB

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
        token = await self._exchange_token(code=code, code_verifier=code_verifier, redirect_uri=redirect_uri)
        profile = await self._get_json(
            _USER_URL,
            token,
            failure=AuthFailureCategory.IDENTITY_VERIFICATION_FAILED,
        )
        if not isinstance(profile, dict):
            raise AuthenticationError(
                "Authentication failed",
                AuthFailureCategory.IDENTITY_VERIFICATION_FAILED,
            )
        subject = self._subject_from_profile(profile)
        emails = await self._get_json(
            _EMAILS_URL,
            token,
            failure=AuthFailureCategory.IDENTITY_VERIFICATION_FAILED,
        )
        email, verified = self._select_email(emails, profile)
        login = profile.get("login")
        name = profile.get("name") or login
        avatar = profile.get("avatar_url")
        return ExternalIdentityData(
            provider=IdentityProvider.GITHUB,
            subject=subject,
            email=email,
            email_verified=verified,
            display_name=str(name) if isinstance(name, str) else None,
            avatar_url=str(avatar) if isinstance(avatar, str) else None,
        )

    async def _exchange_token(self, *, code: str, code_verifier: str, redirect_uri: str) -> str:
        try:
            response = await self._http.post(
                _TOKEN_URL,
                provider="github-oauth",
                headers={"Accept": "application/json"},
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
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
                AuthFailureCategory.CODE_EXCHANGE_FAILED,
            )
        if response.get("error"):
            raise AuthenticationError(
                "Authentication failed",
                AuthFailureCategory.CODE_EXCHANGE_FAILED,
            )
        access_token = response.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise AuthenticationError(
                "Authentication failed",
                AuthFailureCategory.CODE_EXCHANGE_FAILED,
            )
        return access_token

    async def _get_json(self, url: str, token: str, *, failure: AuthFailureCategory) -> object:
        try:
            return await self._http.get(
                url,
                provider="github-oauth",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=self._timeout,
            )
        except ConnectorTimeoutError as exc:
            raise AuthenticationError(
                "Sign-in is temporarily unavailable",
                AuthFailureCategory.PROVIDER_UNAVAILABLE,
                http_status=503,
            ) from exc
        except ConnectorError as exc:
            raise AuthenticationError("Authentication failed", failure) from exc

    @staticmethod
    def _subject_from_profile(profile: dict[str, object]) -> str:
        raw = profile.get("id")
        if isinstance(raw, bool) or raw is None:
            raise AuthenticationError(
                "Authentication failed",
                AuthFailureCategory.IDENTITY_VERIFICATION_FAILED,
            )
        if isinstance(raw, int):
            return str(raw)
        if isinstance(raw, str) and raw.isdigit():
            return raw
        raise AuthenticationError(
            "Authentication failed",
            AuthFailureCategory.IDENTITY_VERIFICATION_FAILED,
        )

    @staticmethod
    def _select_email(emails: object, profile: dict[str, object]) -> tuple[str | None, bool]:
        records: list[dict[str, object]] = []
        if isinstance(emails, list):
            records = [item for item in emails if isinstance(item, dict)]
        verified_primary = [
            item
            for item in records
            if item.get("verified") is True and item.get("primary") is True and isinstance(item.get("email"), str)
        ]
        if verified_primary:
            return str(verified_primary[0]["email"]), True
        verified = [item for item in records if item.get("verified") is True and isinstance(item.get("email"), str)]
        if verified:
            return str(verified[0]["email"]), True
        fallback = profile.get("email")
        if isinstance(fallback, str) and fallback.strip():
            return fallback.strip(), False
        return None, False
