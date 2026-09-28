"""CLI process runner: signals, stderr/stdout, bootstrap, dispatch."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import traceback
from argparse import Namespace
from collections.abc import Awaitable
from contextlib import suppress
from typing import TextIO

from app.interfaces.cli.app import CliApp
from app.interfaces.cli.dispatch import dispatch
from app.interfaces.cli.errors import CliError, map_exception, sanitize_message
from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.cli.render import json_error_payload, write_error, write_json

OUTPUT_ENV = "BYTEBUDDHI_OUTPUT"


def resolve_output_mode(args: Namespace) -> str:
    if getattr(args, "json", False):
        return "json"
    if getattr(args, "output", None):
        return str(args.output)
    env = (os.environ.get(OUTPUT_ENV) or "").strip().lower()
    if env in {"human", "json"}:
        return env
    return "human"


def is_quiet(args: Namespace) -> bool:
    if getattr(args, "quiet", False):
        return True
    return (os.environ.get("BYTEBUDDHI_QUIET") or "").strip().lower() in {"1", "true", "yes"}


async def _await_with_signals(coro: Awaitable[int], app: CliApp | None = None) -> int:
    task: asyncio.Task[int] = asyncio.ensure_future(coro)
    loop = asyncio.get_running_loop()

    def _cancel() -> None:
        if app is not None and app.cancellation_token is not None:
            app.cancellation_token.cancel()
        if not task.done():
            task.cancel()

    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            with suppress(NotImplementedError):
                loop.add_signal_handler(sig, _cancel)
    else:
        signal.signal(signal.SIGINT, lambda _s, _f: loop.call_soon_threadsafe(_cancel))
        with suppress(ValueError, OSError):
            signal.signal(signal.SIGTERM, lambda _s, _f: loop.call_soon_threadsafe(_cancel))
    try:
        return await task
    finally:
        if sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                with suppress(NotImplementedError):
                    loop.remove_signal_handler(sig)


def present_error(
    error: CliError,
    *,
    json_mode: bool,
    debug: bool,
    cause: BaseException | None,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    message = sanitize_message(error.message)
    write_error(message, stream=stderr)
    if json_mode:
        write_json(json_error_payload(message, exit_code=int(error.exit_code)), stream=stdout)
    if debug and cause is not None:
        traceback.print_exception(cause, file=stderr)
    return int(error.exit_code)


async def async_execute(
    args: Namespace,
    *,
    json_mode: bool,
    quiet: bool,
    debug: bool,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    app: CliApp | None = None,
) -> int:
    from app.interfaces.cli.bootstrap import cli_session

    include_runtime = args.command in {"run", "chat"}
    try:
        from app.infrastructure.config.profile import apply_process_profile

        apply_process_profile(getattr(args, "profile", None))
        if args.command == "profile":
            from app.interfaces.cli.profile_data import handle_profile

            return handle_profile(args, json_mode=json_mode, stdout=stdout)
        if args.command == "data":
            from app.interfaces.cli.profile_data import handle_data

            return handle_data(args, json_mode=json_mode, stdout=stdout, stderr=stderr)
        if args.command == "tui":
            from app.interfaces.tui.main import launch_tui

            return await launch_tui(args, stdin=stdin, stderr=stderr, debug=debug)
        if args.command == "update":
            from app.interfaces.cli.update import handle_update

            return handle_update(
                check_only=bool(getattr(args, "check", False)),
                do_rollback=bool(getattr(args, "rollback", False)),
                channel=getattr(args, "channel", "stable") or "stable",
                json_mode=json_mode,
                stdout=stdout,
                stderr=stderr,
            )
        if args.command == "uninstall":
            from app.interfaces.cli.uninstall import handle_uninstall

            return handle_uninstall(
                purge=bool(getattr(args, "purge", False)),
                json_mode=json_mode,
                stdout=stdout,
                stderr=stderr,
            )
        if args.command == "doctor":
            from app.interfaces.cli.doctor import handle_doctor

            return await _await_with_signals(
                handle_doctor(
                    json_mode=json_mode,
                    export_path=getattr(args, "export", None),
                    gateway_url=getattr(args, "gateway_url", None),
                    stdout=stdout,
                    stderr=stderr,
                )
            )
        if args.command in {"login", "logout"}:
            from app.interfaces.cli.oauth_login import login as oauth_login
            from app.interfaces.cli.oauth_login import logout as oauth_logout

            if args.command == "logout":
                return oauth_logout(json_mode=json_mode, stdout=stdout)
            return await oauth_login(
                provider=getattr(args, "provider", None),
                code=getattr(args, "code", None),
                api_url=getattr(args, "api_url", None),
                json_mode=json_mode,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
            )
        if args.command == "gateway":
            from app.interfaces.cli.gateway_dispatch import dispatch_gateway_admin

            return await _await_with_signals(
                dispatch_gateway_admin(args, json_mode=json_mode, debug=debug, stdout=stdout, stderr=stderr)
            )
        if app is None and not _use_embedded(args):
            from app.interfaces.cli.gateway_dispatch import dispatch_via_gateway

            return await _await_with_signals(
                dispatch_via_gateway(
                    args,
                    json_mode=json_mode,
                    quiet=quiet,
                    debug=debug,
                    stdin=stdin,
                    stdout=stdout,
                    stderr=stderr,
                )
            )
        if app is not None:
            return await _await_with_signals(
                dispatch(args, app, json_mode=json_mode, quiet=quiet, stdin=stdin, stderr=stderr),
                app=app,
            )
        async with cli_session(
            include_runtime=include_runtime,
            debug=debug,
            stdout=stdout,
            stderr=stderr,
        ) as session_app:
            return await _await_with_signals(
                dispatch(
                    args,
                    session_app,
                    json_mode=json_mode,
                    quiet=quiet,
                    stdin=stdin,
                    stderr=stderr,
                ),
                app=session_app,
            )
    except CliError as exc:
        return present_error(exc, json_mode=json_mode, debug=debug, cause=exc.__cause__, stdout=stdout, stderr=stderr)
    except asyncio.CancelledError:
        cancelled = CliError("Execution cancelled", ExitCode.TIMEOUT_CANCELLED)
        return present_error(cancelled, json_mode=json_mode, debug=debug, cause=None, stdout=stdout, stderr=stderr)
    except Exception as exc:
        mapped = map_exception(exc)
        return present_error(mapped, json_mode=json_mode, debug=debug, cause=exc, stdout=stdout, stderr=stderr)


def execute(
    args: Namespace,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    app: CliApp | None = None,
) -> int:
    json_mode = resolve_output_mode(args) == "json"
    quiet = is_quiet(args)
    debug = bool(getattr(args, "debug", False))
    if getattr(args, "command", None) == "serve":
        return _serve_foreground(args, stdout=stdout or sys.stdout, stderr=stderr or sys.stderr)
    try:
        return asyncio.run(
            async_execute(
                args,
                json_mode=json_mode,
                quiet=quiet,
                debug=debug,
                stdin=stdin or sys.stdin,
                stdout=stdout or sys.stdout,
                stderr=stderr or sys.stderr,
                app=app,
            )
        )
    except KeyboardInterrupt:
        error = CliError("Execution cancelled", ExitCode.TIMEOUT_CANCELLED)
        return present_error(
            error,
            json_mode=json_mode,
            debug=debug,
            cause=None,
            stdout=stdout or sys.stdout,
            stderr=stderr or sys.stderr,
        )


def _use_embedded(args: Namespace) -> bool:
    """Embedded mode is explicit. Gateway failure must not select it."""
    from app.interfaces.cli.gateway_dispatch import cli_error_from_gateway
    from app.interfaces.gateway.config import resolve_execution_mode
    from app.interfaces.gateway.errors import GatewayConfigError

    try:
        mode = resolve_execution_mode(
            embedded_flag=bool(getattr(args, "embedded", False)),
            gateway_flag=bool(getattr(args, "gateway", False)),
        )
    except GatewayConfigError as exc:
        raise cli_error_from_gateway(exc) from exc
    return mode == "embedded"


def _serve_foreground(args: Namespace, *, stdout: TextIO, stderr: TextIO) -> int:
    from app.interfaces.gateway.errors import GatewayConfigError
    from app.interfaces.gateway.server import run_server

    try:
        return run_server(host=getattr(args, "host", None), port=getattr(args, "port", None))
    except GatewayConfigError as exc:
        from app.interfaces.cli.gateway_dispatch import cli_error_from_gateway

        mapped = cli_error_from_gateway(exc)
        return present_error(mapped, json_mode=False, debug=False, cause=None, stdout=stdout, stderr=stderr)
    except KeyboardInterrupt:
        return int(ExitCode.SUCCESS)
