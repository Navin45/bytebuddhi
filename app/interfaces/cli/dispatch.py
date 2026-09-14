"""Command dispatch over CliApp. No runtime or infrastructure imports."""

from __future__ import annotations

import asyncio
import os
from argparse import Namespace
from typing import TextIO
from uuid import UUID

from app.interfaces.cli.app import CliApp
from app.interfaces.cli.errors import CliError, map_exception
from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.cli.identity import parse_uuid, resolve_user_id

PROJECT_ID_ENV = "BYTEBUDDHI_PROJECT_ID"


def resolve_prompt(args: Namespace) -> str:
    positional = getattr(args, "prompt_pos", None)
    flagged = getattr(args, "prompt", None)
    if positional and flagged:
        raise CliError("Pass the prompt as a positional argument or --prompt, not both", ExitCode.USAGE_ERROR)
    text = (flagged or positional or "").strip()
    if not text:
        raise CliError(
            'A prompt is required. Example: bytebuddhi run "Explain this repository"',
            ExitCode.USAGE_ERROR,
        )
    return text


def optional_prompt(args: Namespace) -> str | None:
    positional = getattr(args, "prompt_pos", None)
    flagged = getattr(args, "prompt", None)
    if positional and flagged:
        raise CliError("Pass the prompt as a positional argument or --prompt, not both", ExitCode.USAGE_ERROR)
    text = (flagged or positional or "").strip()
    return text or None


def resolve_project_arg(args: Namespace) -> UUID | None:
    raw = (getattr(args, "project", None) or os.environ.get(PROJECT_ID_ENV) or "").strip()
    if not raw:
        return None
    return parse_uuid(raw, field="project id")


async def resolve_identity(app: CliApp, args: Namespace) -> tuple[UUID, UUID | None]:
    user_id = await app.authenticate(resolve_user_id(getattr(args, "user_id", None)))
    project_id = await app.resolve_project_id(
        user_id=user_id,
        project_id=resolve_project_arg(args),
        cwd=getattr(args, "cwd", None),
    )
    return user_id, project_id


async def dispatch(
    args: Namespace,
    app: CliApp,
    *,
    json_mode: bool,
    quiet: bool,
    stdin: TextIO,
    stderr: TextIO,
) -> int:
    try:
        command = args.command
        if command == "run":
            user_id, project_id = await resolve_identity(app, args)
            conversation = None
            if getattr(args, "conversation", None):
                conversation = parse_uuid(args.conversation, field="conversation id")
            return await app.run_task(
                prompt=resolve_prompt(args),
                user_id=user_id,
                project_id=project_id,
                conversation_id=conversation,
                json_mode=json_mode,
                quiet=quiet,
                model_provider=getattr(args, "provider", None),
                model_name=getattr(args, "model", None),
            )
        if command == "chat":
            user_id, project_id = await resolve_identity(app, args)
            conversation = None
            if getattr(args, "conversation", None):
                conversation = parse_uuid(args.conversation, field="conversation id")
            return await chat_loop(
                app,
                user_id=user_id,
                project_id=project_id,
                conversation_id=conversation,
                first_prompt=optional_prompt(args),
                json_mode=json_mode,
                quiet=quiet,
                stdin=stdin,
                stderr=stderr,
                model_provider=getattr(args, "provider", None),
                model_name=getattr(args, "model", None),
            )
        if command == "project":
            user_id, _ = await resolve_identity(app, args)
            sub = getattr(args, "project_command", None)
            if sub == "list":
                return await app.list_user_projects(user_id=user_id, json_mode=json_mode)
            if sub == "show":
                project_id = parse_uuid(args.project_id, field="project id")
                return await app.show_project(user_id=user_id, project_id=project_id, json_mode=json_mode)
            raise CliError("Specify a project command: list or show", ExitCode.USAGE_ERROR)
        if command == "health":
            return await app.health(json_mode=json_mode)
        if command == "models":
            return await app.list_models(json_mode=json_mode)
        if command == "login":
            from app.interfaces.cli.oauth_login import login as oauth_login

            return await oauth_login(
                provider=getattr(args, "provider", None),
                code=getattr(args, "code", None),
                api_url=getattr(args, "api_url", None),
                json_mode=json_mode,
                stdin=stdin,
                stdout=app.stdout,
                stderr=stderr,
            )
        if command == "logout":
            from app.interfaces.cli.oauth_login import logout as oauth_logout

            return oauth_logout(json_mode=json_mode, stdout=app.stdout)
        raise CliError(f"Unknown command: {command}", ExitCode.USAGE_ERROR)
    except CliError:
        raise
    except asyncio.CancelledError:
        raise CliError("Execution cancelled", ExitCode.TIMEOUT_CANCELLED) from None
    except Exception as exc:
        raise map_exception(exc) from exc


async def chat_loop(
    app: CliApp,
    *,
    user_id: UUID,
    project_id: UUID | None,
    conversation_id: UUID | None,
    first_prompt: str | None,
    json_mode: bool,
    quiet: bool,
    stdin: TextIO,
    stderr: TextIO,
    model_provider: str | None = None,
    model_name: str | None = None,
) -> int:
    conversation: UUID | str | None = conversation_id
    last_code = int(ExitCode.SUCCESS)
    interactive = stdin.isatty() and not json_mode and not quiet

    async def _turn(prompt: str) -> int:
        nonlocal conversation
        conv = conversation if isinstance(conversation, UUID) else None
        if conv is None and isinstance(conversation, str) and conversation:
            conv = parse_uuid(conversation, field="conversation id")
        code = await app.run_task(
            prompt=prompt,
            user_id=user_id,
            project_id=project_id,
            conversation_id=conv,
            json_mode=json_mode,
            quiet=quiet,
            model_provider=model_provider,
            model_name=model_name,
        )
        if app.last_conversation_id is not None:
            conversation = app.last_conversation_id
        return code

    async def _read_lines_until_eof(initial: str | None) -> int:
        code = last_code
        if initial:
            code = await _turn(initial)
        while True:
            line = stdin.readline()
            if not line:
                break
            text = line.strip()
            if text in {":quit", ":exit", "quit", "exit"}:
                break
            if not text:
                continue
            code = await _turn(text)
        return code

    if not interactive:
        if first_prompt is None:
            line = stdin.readline()
            if not line or not line.strip():
                raise CliError("chat requires a prompt or stdin input", ExitCode.USAGE_ERROR)
            return await _read_lines_until_eof(line.strip())
        return await _read_lines_until_eof(first_prompt)

    if first_prompt:
        last_code = await _turn(first_prompt)

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
        last_code = await _turn(text)
    return last_code
