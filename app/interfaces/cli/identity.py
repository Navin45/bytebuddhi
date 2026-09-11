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
    """Resolve trusted CLI principal: argument, then BYTEBUDDHI_USER_ID.

    The CLI never invents a user id and never reads identity from the prompt.
    """
    raw = (cli_user_id or os.environ.get(USER_ID_ENV) or "").strip()
    if not raw:
        raise CliError(
            "Authentication required: pass --user-id or set BYTEBUDDHI_USER_ID to an existing user UUID",
            ExitCode.AUTH_FAILURE,
        )
    try:
        return UUID(raw)
    except ValueError as exc:
        raise CliError("Invalid user id: must be a UUID", ExitCode.AUTH_FAILURE) from exc
