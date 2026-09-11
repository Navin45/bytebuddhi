"""Argparse CLI surface. No application or infrastructure imports."""

from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version


def package_version() -> str:
    try:
        return version("bytebuddhi")
    except PackageNotFoundError:
        return "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bytebuddhi",
        description=(
            "ByteBuddhi command-line interface. Executes tasks through "
            "ExecuteTaskUseCase; it is not a second agent runtime."
        ),
    )
    parser.add_argument("--version", action="version", version=f"bytebuddhi {package_version()}")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Increase diagnostic logging on stderr. Does not relax authorization or policy.",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress progress on stderr")
    parser.add_argument(
        "--user-id",
        dest="user_id",
        default=None,
        help="Trusted user UUID. Overrides BYTEBUDDHI_USER_ID. Never taken from the prompt.",
    )

    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Execute a single task through ExecuteTaskUseCase")
    run.add_argument("prompt_pos", nargs="?", default=None, help="Task prompt")
    run.add_argument("--prompt", default=None, help="Task prompt (alternative to the positional argument)")
    _add_workspace_args(run)
    run.add_argument("--conversation", default=None, help="Existing conversation UUID")
    _add_io_args(run)

    chat = sub.add_parser("chat", help="Interactive session reusing conversation identity")
    chat.add_argument("prompt_pos", nargs="?", default=None, help="Optional first prompt")
    chat.add_argument("--prompt", default=None, help="Optional first prompt")
    _add_workspace_args(chat)
    chat.add_argument("--conversation", default=None, help="Existing conversation UUID")
    _add_io_args(chat)

    project = sub.add_parser("project", help="Inspect projects owned by the authenticated user")
    project_sub = project.add_subparsers(dest="project_command")
    list_cmd = project_sub.add_parser("list", help="List owned projects")
    _add_io_args(list_cmd)
    show = project_sub.add_parser("show", help="Show one owned project")
    show.add_argument("project_id", help="Project UUID")
    _add_io_args(show)

    health = sub.add_parser("health", help="Read-only health check (no agent execution)")
    _add_io_args(health)
    return parser


def _add_workspace_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project",
        default=None,
        help="Project UUID. Overrides BYTEBUDDHI_PROJECT_ID. Authorized by the application layer.",
    )
    parser.add_argument(
        "--cwd",
        default=None,
        help=("Explicit local project path. Only valid when WORKSPACE_MODE=local and the path "),
    )


def _add_io_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output",
        choices=("human", "json"),
        default=None,
        help="Output format (default: human). JSON is written to stdout only.",
    )
    parser.add_argument("--json", action="store_true", help="Shortcut for --output json")
