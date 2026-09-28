"""CLI identity and argument helpers. No second authentication system."""

import os
from uuid import UUID

from app.interfaces.cli.credentials import StoredCredentials
from app.interfaces.cli.errors import CliError
from app.interfaces.cli.exit_codes import ExitCode

USER_ID_ENV = "BYTEBUDDHI_USER_ID"


def parse_uuid(value: str, *, field: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise CliError(f"Invalid {field}: must be a UUID", ExitCode.USAGE_ERROR) from exc


def resolve_user_id(cli_user_id: str | None) -> UUID:
    """Resolve trusted CLI principal: argument, BYTEBUDDHI_USER_ID, then stored login.

    The CLI never invents a user id and never reads identity from the prompt.
    """
    raw = (cli_user_id or os.environ.get(USER_ID_ENV) or "").strip()
    if raw:
        try:
            return UUID(raw)
        except ValueError as exc:
            raise CliError("Invalid user id: must be a UUID", ExitCode.AUTH_FAILURE) from exc
    from app.interfaces.cli.credentials import load_credentials

    stored = load_credentials()
    if stored is not None:
        _assert_credentials_usable(stored.access_token, stored.refresh_token)
        return stored.user_id
    raise CliError(
        "Authentication required: pass --user-id, set BYTEBUDDHI_USER_ID, or run bytebuddhi login",
        ExitCode.AUTH_FAILURE,
    )


def _assert_credentials_usable(access_token: str, refresh_token: str) -> None:
    from app.infrastructure.auth.jwt_handler import jwt_handler

    if jwt_handler.verify_token(access_token, token_type="access") is not None:
        return
    if jwt_handler.verify_token(refresh_token, token_type="refresh") is not None:
        return
    raise CliError("Session expired. Run bytebuddhi login again.", ExitCode.AUTH_FAILURE)


def current_access_token(api_url: str | None = None) -> str:
    """Return a usable access token, refreshing it when the saved one has expired."""
    from app.infrastructure.auth.jwt_handler import jwt_handler
    from app.interfaces.cli.credentials import CredentialStore

    stored = CredentialStore().load()
    if stored is None or not stored.access_token.strip():
        raise CliError("Authentication required. Run bytebuddhi login.", ExitCode.AUTH_FAILURE)
    if jwt_handler.verify_token(stored.access_token, token_type="access") is not None:
        return stored.access_token.strip()
    if jwt_handler.verify_token(stored.refresh_token, token_type="refresh") is None:
        raise CliError("Session expired. Run bytebuddhi login again.", ExitCode.AUTH_FAILURE)
    refreshed = _refresh_credentials(stored, api_url=api_url)
    CredentialStore().save(refreshed)
    return refreshed.access_token


def _refresh_credentials(stored: StoredCredentials, *, api_url: str | None) -> StoredCredentials:
    import httpx

    from app.interfaces.cli.oauth_login import resolve_api_url

    base = resolve_api_url(api_url)
    try:
        response = httpx.post(
            f"{base}/api/v1/auth/refresh",
            json={"refresh_token": stored.refresh_token},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise CliError("Could not refresh the saved session.", ExitCode.AUTH_FAILURE) from exc
    if response.status_code >= 400:
        raise CliError("Session expired. Run bytebuddhi login again.", ExitCode.AUTH_FAILURE)
    body = response.json()
    access = body.get("access_token") if isinstance(body, dict) else None
    refresh = body.get("refresh_token") if isinstance(body, dict) else None
    if not isinstance(access, str) or not isinstance(refresh, str):
        raise CliError("Session expired. Run bytebuddhi login again.", ExitCode.AUTH_FAILURE)
    return StoredCredentials(
        user_id=stored.user_id,
        access_token=access,
        refresh_token=refresh,
    )
