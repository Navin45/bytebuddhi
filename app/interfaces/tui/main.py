"""Launch the terminal client through the existing gateway."""

from __future__ import annotations

import sys
from argparse import Namespace
from typing import TextIO

from app.infrastructure.config.logger import setup_logging
from app.interfaces.cli.credentials import CredentialStore
from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.cli.gateway_dispatch import _ensure_local_gateway
from app.interfaces.gateway.client import GatewayClient
from app.interfaces.gateway.config import resolve_gateway_endpoint
from app.interfaces.gateway.errors import GatewayConfigError, GatewayError
from app.interfaces.tui.app import ByteBuddhiApp
from app.interfaces.tui.session import GatewaySession


async def launch_tui(args: Namespace, *, stdin: TextIO, stderr: TextIO, debug: bool = False) -> int:
    """Open the TUI. Embedded execution is not a fallback."""
    setup_logging(level="DEBUG" if debug else "INFO", stream=stderr)
    if not _interactive(stdin):
        stderr.write("bytebuddhi tui needs an interactive terminal.\n")
        return int(ExitCode.USAGE_ERROR)
    try:
        endpoint = resolve_gateway_endpoint(getattr(args, "gateway_url", None))
    except GatewayConfigError as exc:
        stderr.write(f"{exc.message}\n")
        return int(ExitCode.USAGE_ERROR if exc.usage else ExitCode.CONFIG_FAILURE)
    if endpoint.local and not getattr(args, "no_start_gateway", False):
        stderr.write("GATEWAY STARTING\n")
        try:
            await _ensure_local_gateway(stderr)
        except GatewayError as exc:
            stderr.write(f"{exc.message}\n")
            stderr.write("Cannot connect to the ByteBuddhi gateway.\n")
            return int(ExitCode.CONFIG_FAILURE)
    token = _token()
    if token is None:
        stderr.write("Authentication required. Run `bytebuddhi login`.\n")
        return int(ExitCode.AUTH_FAILURE)
    client = GatewayClient(endpoint.url, token=token, local_gateway=endpoint.local, debug=debug)
    app = ByteBuddhiApp(GatewaySession(client), project_id=getattr(args, "project", None))
    try:
        await app.run_async()
    finally:
        await app.session.aclose()
    return int(ExitCode.SUCCESS)


def _token() -> str | None:
    stored = CredentialStore().load()
    if stored is None:
        return None
    token = stored.access_token.strip()
    return token or None


def _interactive(stdin: TextIO) -> bool:
    isatty = getattr(stdin, "isatty", None)
    if callable(isatty):
        return bool(isatty())
    return bool(getattr(sys.stdin, "isatty", lambda: False)())
