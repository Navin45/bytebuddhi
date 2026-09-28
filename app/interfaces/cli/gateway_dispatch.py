"""Gateway-mode CLI. Talks to FastAPI through GatewayClient and does not build a runtime."""

from __future__ import annotations

import asyncio
import os
from argparse import Namespace
from typing import Any, TextIO
from uuid import UUID, uuid4

from app.infrastructure.config.logger import setup_logging
from app.interfaces.cli.credentials import CredentialStore
from app.interfaces.cli.dispatch import optional_prompt, resolve_project_arg, resolve_prompt
from app.interfaces.cli.errors import CliError
from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.cli.identity import current_access_token, parse_uuid
from app.interfaces.cli.render import (
    json_health_payload,
    json_models_payload,
    json_project_payload,
    json_projects_payload,
    write_error,
    write_human_models,
    write_human_project,
    write_human_projects,
    write_json,
    write_progress,
)
from app.interfaces.gateway.client import GatewayClient
from app.interfaces.gateway.config import config_dir, resolve_bind_address, resolve_gateway_endpoint
from app.interfaces.gateway.errors import (
    AuthenticationRequired,
    AuthorizationDenied,
    GatewayConfigError,
    GatewayError,
    GatewayPortConflict,
    GatewayStartFailed,
    GatewayStartTimeout,
    GatewayTimeout,
    GatewayUnavailable,
    InvalidRequest,
    ResourceNotFound,
)
from app.interfaces.gateway.manager import GatewayManager
from app.interfaces.gateway.models import GatewayStatus

USER_ID_ENV = "BYTEBUDDHI_USER_ID"


def cli_error_from_gateway(exc: GatewayError) -> CliError:
    if isinstance(exc, GatewayConfigError):
        code = ExitCode.USAGE_ERROR if exc.usage else ExitCode.CONFIG_FAILURE
        return CliError(exc.message, code)
    if isinstance(exc, (AuthenticationRequired, AuthorizationDenied)):
        return CliError(exc.message, ExitCode.AUTH_FAILURE)
    if isinstance(exc, ResourceNotFound):
        return CliError(exc.message, ExitCode.WORKSPACE_FAILURE)
    if isinstance(exc, InvalidRequest):
        return CliError(exc.message, ExitCode.USAGE_ERROR)
    if isinstance(exc, GatewayTimeout):
        return CliError(exc.message, ExitCode.TIMEOUT_CANCELLED)
    if isinstance(exc, (GatewayPortConflict, GatewayStartFailed, GatewayStartTimeout)):
        return CliError(exc.message, ExitCode.CONFIG_FAILURE)
    if isinstance(exc, GatewayUnavailable):
        return CliError(exc.message, ExitCode.EXECUTION_FAILURE)
    return CliError(exc.message, ExitCode.EXECUTION_FAILURE)


async def dispatch_gateway_admin(
    args: Namespace,
    *,
    json_mode: bool,
    debug: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    _configure_logging(debug=debug, stderr=stderr)
    sub = getattr(args, "gateway_command", None)
    if sub not in {"start", "stop", "status", "restart"}:
        raise CliError("Specify a gateway command: start, stop, status, or restart", ExitCode.USAGE_ERROR)
    try:
        bind = resolve_bind_address(getattr(args, "host", None), getattr(args, "port", None))
    except GatewayConfigError as exc:
        raise cli_error_from_gateway(exc) from exc
    if bind.exposed and sub in {"start", "restart"}:
        stderr.write(f"warning: binding {bind.host} is not loopback. The default local gateway is 127.0.0.1.\n")
    manager = GatewayManager(bind, directory=config_dir())
    try:
        if sub == "start":
            status = await manager.start()
        elif sub == "stop":
            status = await manager.stop()
        elif sub == "restart":
            status = await manager.restart()
        else:
            status = await manager.status()
    except GatewayError as exc:
        raise cli_error_from_gateway(exc) from exc
    _write_status(status, json_mode=json_mode, stdout=stdout)
    if sub == "stop" and "unknown process" in status.message:
        return int(ExitCode.EXECUTION_FAILURE)
    if sub == "status" and not status.process_running:
        return int(ExitCode.SUCCESS)
    return int(ExitCode.SUCCESS)


async def dispatch_via_gateway(
    args: Namespace,
    *,
    json_mode: bool,
    quiet: bool,
    debug: bool,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Execute a user command through the gateway. Does not fall back to embedded mode."""
    _configure_logging(debug=debug, stderr=stderr)
    try:
        endpoint = resolve_gateway_endpoint(getattr(args, "gateway_url", None))
    except GatewayConfigError as exc:
        raise cli_error_from_gateway(exc) from exc
    cwd = getattr(args, "cwd", None)
    if cwd and not endpoint.local:
        raise CliError(
            "--cwd is only valid against the local gateway. Remote gateways cannot use a path from this machine.",
            ExitCode.WORKSPACE_FAILURE,
        )
    if endpoint.local and not getattr(args, "no_start_gateway", False):
        await _ensure_local_gateway(stderr)
    token = _token_for(args)
    async with GatewayClient(
        endpoint.url,
        token=token,
        local_gateway=endpoint.local,
        debug=debug,
    ) as client:
        command = args.command
        if command == "run":
            return await _run(
                client,
                args,
                json_mode=json_mode,
                quiet=quiet,
                stdout=stdout,
                stderr=stderr,
                conversation_id=_optional_uuid(getattr(args, "conversation", None), field="conversation id"),
            )
        if command == "chat":
            return await _chat(
                client,
                args,
                json_mode=json_mode,
                quiet=quiet,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
            )
        if command == "project":
            return await _project(client, args, json_mode=json_mode, stdout=stdout)
        if command == "health":
            return await _health(client, json_mode=json_mode, stdout=stdout)
        if command == "models":
            return await _models(client, json_mode=json_mode, stdout=stdout)
        raise CliError(f"Unknown command: {command}", ExitCode.USAGE_ERROR)


async def _ensure_local_gateway(stderr: TextIO) -> None:
    bind = resolve_bind_address(None, None)
    manager = GatewayManager(bind, directory=config_dir())
    try:
        status = await manager.ensure_running()
    except GatewayError as exc:
        raise cli_error_from_gateway(exc) from exc
    if not status.ready:
        raise CliError(
            f"Local gateway at {bind.url} is not ready. ByteBuddhi will not switch to embedded mode.",
            ExitCode.CONFIG_FAILURE,
        )


def _token_for(args: Namespace) -> str | None:
    if args.command == "health":
        stored = CredentialStore().load()
        if stored is None:
            return None
        return stored.access_token.strip() or None
    return _required_token(args)


def _required_token(args: Namespace) -> str:
    try:
        return current_access_token(getattr(args, "gateway_url", None))
    except CliError as exc:
        if getattr(args, "user_id", None) or (os.environ.get(USER_ID_ENV) or "").strip():
            raise CliError(
                f"{exc.message} --user-id applies to --embedded mode and is not sent to the gateway.",
                exc.exit_code,
            ) from exc
        raise


async def _run(
    client: GatewayClient,
    args: Namespace,
    *,
    json_mode: bool,
    quiet: bool,
    stdout: TextIO,
    stderr: TextIO,
    conversation_id: UUID | None,
) -> int:
    project_id = await _project_id(client, args)
    code, _conversation = await _stream_turn(
        client,
        prompt=resolve_prompt(args),
        project_id=project_id,
        conversation_id=conversation_id,
        provider=getattr(args, "provider", None),
        model_name=getattr(args, "model", None),
        json_mode=json_mode,
        quiet=quiet,
        stdout=stdout,
        stderr=stderr,
    )
    return code


async def _stream_turn(
    client: GatewayClient,
    *,
    prompt: str,
    project_id: UUID | None,
    conversation_id: UUID | None,
    provider: str | None,
    model_name: str | None,
    json_mode: bool,
    quiet: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> tuple[int, UUID | None]:
    write_progress("Running task...", quiet=quiet, json_mode=json_mode, stream=stderr)
    try:
        accepted = await client.create_run(
            prompt=prompt,
            project_id=project_id,
            conversation_id=conversation_id,
            model_provider=provider,
            model_name=model_name,
            idempotency_key=str(uuid4()),
        )
    except GatewayError as exc:
        raise cli_error_from_gateway(exc) from exc
    code = int(ExitCode.SUCCESS)
    try:
        async for event in client.stream_run(accepted.run_id):
            rendered = _render_stream_event(event, json_mode=json_mode, quiet=quiet, stdout=stdout, stderr=stderr)
            if rendered is not None:
                code = rendered
            found = _conversation_from_event(event)
            if found is not None:
                conversation_id = found
    except asyncio.CancelledError:
        await _cancel_on_interrupt(client, accepted.run_id)
        raise
    except GatewayError as exc:
        raise cli_error_from_gateway(exc) from exc
    if not json_mode:
        stdout.write("\n")
    return code, conversation_id


async def _chat(
    client: GatewayClient,
    args: Namespace,
    *,
    json_mode: bool,
    quiet: bool,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    project_id = await _project_id(client, args)
    conversation = _optional_uuid(getattr(args, "conversation", None), field="conversation id")
    provider = getattr(args, "provider", None)
    model_name = getattr(args, "model", None)
    interactive = stdin.isatty() and not json_mode and not quiet
    last_code = int(ExitCode.SUCCESS)

    async def turn(prompt: str) -> int:
        nonlocal conversation
        code, found = await _stream_turn(
            client,
            prompt=prompt,
            project_id=project_id,
            conversation_id=conversation,
            provider=provider,
            model_name=model_name,
            json_mode=json_mode,
            quiet=quiet,
            stdout=stdout,
            stderr=stderr,
        )
        if found is not None:
            conversation = found
        return code

    first = optional_prompt(args)
    if not interactive:
        if first is None:
            line = stdin.readline()
            if not line or not line.strip():
                raise CliError("chat requires a prompt or stdin input", ExitCode.USAGE_ERROR)
            first = line.strip()
        last_code = await turn(first)
        while True:
            line = stdin.readline()
            if not line:
                break
            text = line.strip()
            if text in {":quit", ":exit", "quit", "exit"}:
                break
            if not text:
                continue
            last_code = await turn(text)
        return last_code

    if first:
        last_code = await turn(first)
    while True:
        stderr.write("bytebuddhi> ")
        stderr.flush()
        line = stdin.readline()
        if not line:
            break
        text = line.strip()
        if not text:
            continue
        if text in {":quit", ":exit", "quit", "exit"}:
            break
        last_code = await turn(text)
    return last_code


async def _project(client: GatewayClient, args: Namespace, *, json_mode: bool, stdout: TextIO) -> int:
    sub = getattr(args, "project_command", None)
    try:
        if sub == "list":
            projects = await client.list_projects()
            if json_mode:
                write_json(json_projects_payload(projects), stream=stdout)
            else:
                write_human_projects(projects, stream=stdout)
            return int(ExitCode.SUCCESS)
        if sub == "show":
            project_id = parse_uuid(args.project_id, field="project id")
            project = await client.get_project(project_id)
            if json_mode:
                write_json(json_project_payload(project), stream=stdout)
            else:
                write_human_project(project, stream=stdout)
            return int(ExitCode.SUCCESS)
    except GatewayError as exc:
        raise cli_error_from_gateway(exc) from exc
    raise CliError("Specify a project command: list or show", ExitCode.USAGE_ERROR)


async def _health(client: GatewayClient, *, json_mode: bool, stdout: TextIO) -> int:
    try:
        live = await client.health()
        ready = await client.readiness()
    except GatewayError as exc:
        raise cli_error_from_gateway(exc) from exc
    payload = {
        "status": "healthy" if ready.ready else "unhealthy",
        "service": live.service or "bytebuddhi-gateway",
        "version": live.version,
        "readiness": ready.status,
        "url": client.base_url,
    }
    if json_mode:
        write_json(json_health_payload(payload), stream=stdout)
    else:
        stdout.write(f"status: {payload['status']}\n")
        for key, value in payload.items():
            if key == "status":
                continue
            stdout.write(f"{key}: {value}\n")
    healthy = payload["status"] == "healthy"
    return int(ExitCode.SUCCESS if healthy else ExitCode.EXECUTION_FAILURE)


async def _models(client: GatewayClient, *, json_mode: bool, stdout: TextIO) -> int:
    try:
        catalog = await client.list_models()
    except GatewayError as exc:
        raise cli_error_from_gateway(exc) from exc
    models = [
        {
            "provider": item.provider,
            "model": item.model,
            "display_name": item.display_name,
            "available": item.available,
            "capabilities": list(item.capabilities),
        }
        for item in catalog.models
    ]
    if json_mode:
        write_json(
            json_models_payload(
                default_provider=catalog.default_provider,
                default_model=catalog.default_model,
                models=models,
            ),
            stream=stdout,
        )
    else:
        write_human_models(
            default_provider=catalog.default_provider,
            default_model=catalog.default_model,
            models=models,
            stream=stdout,
        )
    return int(ExitCode.SUCCESS)


async def _project_id(client: GatewayClient, args: Namespace) -> UUID | None:
    project_id = resolve_project_arg(args)
    cwd = getattr(args, "cwd", None)
    if project_id is not None and cwd:
        raise CliError("Use either --project or --cwd, not both", ExitCode.USAGE_ERROR)
    if not cwd:
        return project_id
    try:
        return await client.resolve_local_project(str(cwd))
    except GatewayError as exc:
        raise cli_error_from_gateway(exc) from exc


def _render_stream_event(
    event: dict[str, Any],
    *,
    json_mode: bool,
    quiet: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    event_type = str(event.get("type") or "")
    data = _event_data(event)
    if json_mode:
        write_json(event, stream=stdout)
    elif event_type == "assistant_delta":
        stdout.write(str(data.get("delta") or ""))
        stdout.flush()
    elif event_type == "tool_started":
        name = str(data.get("tool_name") or "")
        if name:
            write_progress(f"Tool: {name}", quiet=quiet, json_mode=False, stream=stderr)
    elif event_type == "run_failed":
        message = str(data.get("error_message") or "Run execution failed")
        write_error(message, stream=stderr)
    elif event_type == "run_interrupted":
        message = str(data.get("error_message") or "The worker lease expired and the run was not replayed")
        write_error(message, stream=stderr)
    if event_type == "run_completed":
        return int(ExitCode.SUCCESS)
    if event_type == "run_cancelled":
        return int(ExitCode.TIMEOUT_CANCELLED)
    if event_type in {"run_failed", "run_interrupted"}:
        return int(ExitCode.EXECUTION_FAILURE)
    return None


def _event_data(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("data")
    if isinstance(raw, dict):
        return raw
    return {}


def _conversation_from_event(event: dict[str, Any]) -> UUID | None:
    raw = _event_data(event).get("conversation_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


async def _cancel_on_interrupt(client: GatewayClient, run_id: str) -> None:
    cleanup = asyncio.create_task(client.cancel_run(run_id))
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            continue


def _optional_uuid(value: str | None, *, field: str) -> UUID | None:
    if not value:
        return None
    return parse_uuid(value, field=field)


def _write_status(status: GatewayStatus, *, json_mode: bool, stdout: TextIO) -> None:
    if json_mode:
        write_json(status.as_dict(), stream=stdout)
        return
    pid = "-" if status.pid is None else str(status.pid)
    version = status.version or "-"
    uptime = "-" if status.uptime_seconds is None else str(status.uptime_seconds)
    stdout.write(
        "\n".join(
            [
                f"running: {'yes' if status.process_running else 'no'}",
                f"pid: {pid}",
                f"url: {status.url}",
                f"ready: {'yes' if status.ready else 'no'}",
                f"version: {version}",
                f"uptime_seconds: {uptime}",
                f"message: {status.message}",
            ]
        )
        + "\n"
    )


def _configure_logging(*, debug: bool, stderr: TextIO) -> None:
    try:
        setup_logging(stream=stderr, level="DEBUG" if debug else None)
    except Exception as exc:
        write_error(f"Logging setup failed: {exc}", stream=stderr)
