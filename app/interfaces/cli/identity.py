"""CLI identity and argument helpers. No second authentication system."""

import os
from uuid import UUID

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
