"""Google ID token verification using the official google-auth library."""

from typing import Any, Protocol


class IdTokenVerifier(Protocol):
    def verify(self, token: str, audience: str) -> dict[str, Any]:
        """Verify signature, issuer, audience, and expiry. Returns claims."""


class GoogleIdTokenVerifier:
    """google-auth OIDC verification. Do not replace with unsigned JWT decode."""

    def verify(self, token: str, audience: str) -> dict[str, Any]:
        from google.auth.transport import requests as google_requests  # type: ignore[import-untyped]
        from google.oauth2 import id_token  # type: ignore[import-untyped]

        claims = id_token.verify_oauth2_token(token, google_requests.Request(), audience=audience)
        return dict(claims)
