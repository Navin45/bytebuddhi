"""Browser-based CLI OAuth login against the ByteBuddhi API. No client secrets."""

from __future__ import annotations

import os
import webbrowser
from contextlib import suppress
from typing import TextIO
from uuid import UUID

import httpx

from app.domain.value_objects.identity_provider import IdentityProvider
from app.interfaces.cli.credentials import StoredCredentials, delete_credentials, save_credentials
from app.interfaces.cli.errors import CliError
from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.cli.render import write_json

_API_ENV = "BYTEBUDDHI_API_URL"


def resolve_api_url(cli_api_url: str | None) -> str:
    raw = (cli_api_url or os.environ.get(_API_ENV) or "http://127.0.0.1:8000").strip().rstrip("/")
    if not raw.startswith("http://") and not raw.startswith("https://"):
        raise CliError("API URL must be an http(s) URL", ExitCode.USAGE_ERROR)
    return raw


def parse_login_provider(raw: str | None) -> IdentityProvider:
    value = (raw or "").strip().lower()
    try:
        return IdentityProvider(value)
    except ValueError as exc:
        raise CliError("Provider must be google or github", ExitCode.USAGE_ERROR) from exc


async def login(
    *,
    provider: str | None,
    code: str | None,
    api_url: str | None,
    json_mode: bool,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    base = resolve_api_url(api_url)
    exchange_code = (code or "").strip()
    if not exchange_code:
        identity = parse_login_provider(provider)
        login_url = f"{base}/api/v1/auth/{identity.value}/login?client=cli"
        stderr.write(f"Open this URL to sign in:\n{login_url}\n")
        stderr.flush()
        with suppress(Exception):
            webbrowser.open(login_url)
        if stdin.isatty():
            stderr.write("Paste the one-time code: ")
            stderr.flush()
            exchange_code = stdin.readline().strip()
        if not exchange_code:
            raise CliError("A one-time code is required. Re-run with --code after signing in.", ExitCode.USAGE_ERROR)
    tokens = await _exchange(base, exchange_code)
    user_id = await _fetch_user_id(base, tokens["access_token"])
    save_credentials(
        StoredCredentials(
            user_id=user_id,
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
        )
    )
    if json_mode:
        write_json({"status": "signed_in", "user_id": str(user_id)}, stream=stdout)
    else:
        stdout.write(f"Signed in as {user_id}\n")
    return int(ExitCode.SUCCESS)


def logout(*, json_mode: bool, stdout: TextIO) -> int:
    deleted = delete_credentials()
    if json_mode:
        write_json({"status": "signed_out", "had_credentials": deleted}, stream=stdout)
    else:
        stdout.write("Signed out\n")
    return int(ExitCode.SUCCESS)


async def _exchange(api_url: str, code: str) -> dict[str, str]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{api_url}/api/v1/auth/oauth/exchange", json={"code": code})
    except httpx.HTTPError as exc:
        raise CliError("Could not reach the ByteBuddhi API", ExitCode.AUTH_FAILURE) from exc
    if response.status_code >= 400:
        raise CliError("Sign-in failed or the code expired", ExitCode.AUTH_FAILURE)
    body = response.json()
    access = body.get("access_token")
    refresh = body.get("refresh_token")
    if not isinstance(access, str) or not isinstance(refresh, str):
        raise CliError("Sign-in failed", ExitCode.AUTH_FAILURE)
    return {"access_token": access, "refresh_token": refresh}


async def _fetch_user_id(api_url: str, access_token: str) -> UUID:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{api_url}/api/v1/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.HTTPError as exc:
        raise CliError("Could not reach the ByteBuddhi API", ExitCode.AUTH_FAILURE) from exc
    if response.status_code >= 400:
        raise CliError("Sign-in failed", ExitCode.AUTH_FAILURE)
    user_id = response.json().get("id")
    try:
        return UUID(str(user_id))
    except (ValueError, TypeError) as exc:
        raise CliError("Sign-in failed", ExitCode.AUTH_FAILURE) from exc
