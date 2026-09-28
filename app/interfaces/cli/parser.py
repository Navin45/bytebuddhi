"""Argparse CLI surface. No application or infrastructure imports."""

from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version

from app import __version__ as fallback_version


def package_version() -> str:
    try:
        return version("bytebuddhi")
    except PackageNotFoundError:
        return fallback_version


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bytebuddhi",
        description=(
            "ByteBuddhi command-line interface. Gateway mode calls the ByteBuddhi API. "
            "Embedded mode (--embedded) calls application use cases in-process."
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
        "--profile",
        choices=("server", "standalone"),
        default=None,
        help="Storage profile. standalone uses SQLite and does not require PostgreSQL or Redis.",
    )
    parser.add_argument(
        "--user-id",
        dest="user_id",
        default=None,
        help="Embedded mode only. Trusted user UUID. Overrides BYTEBUDDHI_USER_ID. Not sent to the gateway.",
    )

    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Execute a single task through the gateway")
    run.add_argument("prompt_pos", nargs="?", default=None, help="Task prompt")
    run.add_argument("--prompt", default=None, help="Task prompt (alternative to the positional argument)")
    _add_workspace_args(run)
    run.add_argument("--conversation", default=None, help="Existing conversation UUID")
    _add_model_args(run)
    _add_transport_args(run)
    _add_io_args(run)

    tui = sub.add_parser("tui", help="Open the terminal interface through the gateway")
    tui.add_argument("--project", default=None, help="Project UUID to select")
    tui.add_argument("--gateway-url", default=None, help="Gateway origin. Same precedence as the other commands.")
    tui.add_argument(
        "--no-start-gateway",
        action="store_true",
        help="Do not start a local gateway automatically.",
    )

    chat = sub.add_parser("chat", help="Interactive session reusing conversation identity")
    chat.add_argument("prompt_pos", nargs="?", default=None, help="Optional first prompt")
    chat.add_argument("--prompt", default=None, help="Optional first prompt")
    _add_workspace_args(chat)
    chat.add_argument("--conversation", default=None, help="Existing conversation UUID")
    _add_model_args(chat)
    _add_transport_args(chat)
    _add_io_args(chat)

    project = sub.add_parser("project", help="Inspect projects owned by the authenticated user")
    project_sub = project.add_subparsers(dest="project_command")
    list_cmd = project_sub.add_parser("list", help="List owned projects")
    _add_transport_args(list_cmd)
    _add_io_args(list_cmd)
    show = project_sub.add_parser("show", help="Show one owned project")
    show.add_argument("project_id", help="Project UUID")
    _add_transport_args(show)
    _add_io_args(show)

    health = sub.add_parser("health", help="Read gateway liveness and readiness")
    _add_transport_args(health)
    _add_io_args(health)

    models = sub.add_parser("models", help="List models from the gateway catalog")
    _add_transport_args(models)
    _add_io_args(models)

    serve = sub.add_parser("serve", help="Run the FastAPI app in the foreground as a local gateway")
    serve.add_argument("--host", default=None, help="Bind host. Default 127.0.0.1. 0.0.0.0 only when explicit.")
    serve.add_argument("--port", type=int, default=None, help="Bind port. Default 8765.")

    gateway = sub.add_parser("gateway", help="Manage the local gateway process")
    gateway_sub = gateway.add_subparsers(dest="gateway_command")
    for name, help_text in (
        ("start", "Start the local gateway and wait until it is ready"),
        ("stop", "Stop the gateway process started by this CLI"),
        ("status", "Show process state, readiness, PID, URL, and version"),
        ("restart", "Stop the managed gateway, then start it again"),
    ):
        command = gateway_sub.add_parser(name, help=help_text)
        if name in {"start", "restart"}:
            command.add_argument("--host", default=None)
            command.add_argument("--port", type=int, default=None)
        _add_io_args(command)

    login = sub.add_parser("login", help="Sign in with Google or GitHub via the ByteBuddhi API")
    login.add_argument("--provider", choices=("google", "github"), default=None, help="Identity provider")
    login.add_argument("--code", default=None, help="One-time exchange code from the browser sign-in page")
    login.add_argument(
        "--api-url",
        default=None,
        help=(
            "Gateway or API origin. Overrides BYTEBUDDHI_GATEWAY_URL and BYTEBUDDHI_API_URL. "
            "Default is the local gateway."
        ),
    )
    _add_io_args(login)

    logout = sub.add_parser("logout", help="Remove stored ByteBuddhi credentials from this machine")
    _add_io_args(logout)

    update = sub.add_parser("update", help="Check for, install, or rollback CLI updates")
    update.add_argument("--check", action="store_true", help="Show available updates without installing")
    update.add_argument("--rollback", action="store_true", help="Revert to the previous installed version")
    update.add_argument("--channel", choices=("stable", "beta"), default="stable", help="Update channel")
    _add_io_args(update)

    uninstall_cmd = sub.add_parser("uninstall", help="Remove the managed CLI installation")
    uninstall_cmd.add_argument(
        "--purge",
        action="store_true",
        help="Also remove config, credentials, and all user data",
    )
    _add_io_args(uninstall_cmd)

    profile_cmd = sub.add_parser("profile", help="Show or set the persisted storage profile")
    profile_sub = profile_cmd.add_subparsers(dest="profile_action")
    profile_sub.add_parser("show", help="Show the active profile")
    profile_set = profile_sub.add_parser("set", help="Persist server or standalone")
    profile_set.add_argument("name", choices=("server", "standalone"))
    _add_io_args(profile_cmd)

    data_cmd = sub.add_parser("data", help="Backup or explicitly migrate local data")
    data_sub = data_cmd.add_subparsers(dest="data_action")
    backup = data_sub.add_parser("backup", help="Export a standalone backup without credentials")
    backup.add_argument("path", nargs="?", default=None, help="Destination zip path")
    backup.add_argument("--include-artifacts", action="store_true", help="Include local artifact files")
    migrate = data_sub.add_parser("migrate", help="Copy PostgreSQL rows into a new standalone database")
    migrate.add_argument(
        "--to-standalone", action="store_true", help="Required confirmation of the destination profile"
    )
    migrate.add_argument("--source", default=None, help="Source PostgreSQL URL. Defaults to DATABASE_URL.")
    migrate.add_argument("--yes", action="store_true", help="Replace an existing standalone database")
    _add_io_args(data_cmd)

    doctor = sub.add_parser("doctor", help="Run operational diagnostics and health checks")
    doctor.add_argument("--gateway-url", default=None, help="Gateway origin to test")
    doctor.add_argument("--export", default=None, help="Export sanitized diagnostics bundle to a zip file")
    _add_io_args(doctor)
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
        help=("Explicit local project path. Only valid against the local gateway when WORKSPACE_MODE=local."),
    )


def _add_transport_args(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--embedded",
        action="store_true",
        help="In-process execution. Not the default, and never a fallback when the gateway is down.",
    )
    mode.add_argument(
        "--gateway",
        action="store_true",
        help="Force gateway mode when BYTEBUDDHI_EXECUTION_MODE=embedded.",
    )
    parser.add_argument(
        "--gateway-url",
        default=None,
        help="Gateway origin. Overrides BYTEBUDDHI_GATEWAY_URL and BYTEBUDDHI_API_URL.",
    )
    parser.add_argument(
        "--no-start-gateway",
        action="store_true",
        help="Do not start a local gateway automatically.",
    )


def _add_model_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--provider",
        default=None,
        help="Catalog provider id (with --model). Does not accept endpoints or API keys.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Catalog model id. Must be enabled and available. Default comes from server config.",
    )


def _add_io_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output",
        choices=("human", "json"),
        default=None,
        help="Output format (default: human). JSON is written to stdout only.",
    )
    parser.add_argument("--json", action="store_true", help="Shortcut for --output json")
