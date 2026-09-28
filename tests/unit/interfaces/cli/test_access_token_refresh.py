from uuid import UUID

import httpx

from app.infrastructure.auth.jwt_handler import jwt_handler
from app.interfaces.cli.credentials import StoredCredentials
from app.interfaces.cli.identity import current_access_token


def test_expired_access_token_is_refreshed(monkeypatch):
    user_id = UUID("c0b9bfde-ff8f-4161-9ab1-b3de99835a60")
    stored = StoredCredentials(user_id=user_id, access_token="expired-access", refresh_token="valid-refresh")
    saved: dict[str, StoredCredentials] = {}

    class Store:
        def load(self) -> StoredCredentials:
            return stored

        def save(self, credentials: StoredCredentials) -> None:
            saved["credentials"] = credentials

    def verify(token: str, token_type: str = "access") -> UUID | None:
        if token_type == "refresh" and token == "valid-refresh":
            return user_id
        return None

    class Response:
        status_code = 200

        def json(self) -> dict[str, str]:
            return {"access_token": "new-access", "refresh_token": "new-refresh"}

    monkeypatch.setattr("app.interfaces.cli.credentials.CredentialStore", Store)
    monkeypatch.setattr(jwt_handler, "verify_token", verify)
    monkeypatch.setattr("app.interfaces.cli.oauth_login.resolve_api_url", lambda _url: "http://127.0.0.1:8765")
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: Response())

    assert current_access_token() == "new-access"
    assert saved["credentials"].access_token == "new-access"
    assert saved["credentials"].refresh_token == "new-refresh"
