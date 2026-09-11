"""ByteBuddhi CLI entry point."""

from __future__ import annotations

from collections.abc import Sequence

from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.cli.parser import build_parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arg_list = list(argv) if argv is not None else None
    try:
        args = parser.parse_args(arg_list)
    except SystemExit as exc:
        code = exc.code
        if code in {0, None}:
            return int(ExitCode.SUCCESS)
        return int(ExitCode.USAGE_ERROR)

    if not args.command:
        parser.print_help()
        return int(ExitCode.USAGE_ERROR)

    from app.interfaces.cli.runner import execute

    return execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
