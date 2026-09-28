#!/usr/bin/env python3
"""Generate ``release.json`` for a tagged release.

Usage
-----
    python scripts/release_manifest.py --version 0.1.4 --commit abc123 \\
        --artifact "python_wheel:bytebuddhi-0.1.4-py3-none-any.whl:SHA256HASH:URL" \\
        --artifact "windows_exe:ByteBuddhi-Setup-0.1.4.exe:SHA256HASH:URL"

The output is written to ``release.json`` in the current directory or to
the path specified by ``--output``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate release.json")
    parser.add_argument("--version", required=True, help="Semantic version (e.g. 0.1.4)")
    parser.add_argument("--commit", required=True, help="Full git commit SHA")
    parser.add_argument("--protocol-version", type=int, default=1, help="Run/event protocol version")
    parser.add_argument("--min-python", default="3.13", help="Minimum Python version")
    parser.add_argument("--channel", default="stable", help="Release channel (stable / beta)")
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="TYPE:FILENAME:SHA256:URL",
        help="Artifact entry (repeatable)",
    )
    parser.add_argument("--output", default="release.json", help="Output file path")
    args = parser.parse_args()

    artifacts = []
    for spec in args.artifact:
        parts = spec.split(":", 3)
        if len(parts) != 4:
            print(f"ERROR: artifact must be TYPE:FILENAME:SHA256:URL — got: {spec}", file=sys.stderr)
            return 1
        art_type, filename, sha256, url = parts
        artifacts.append(
            {
                "type": art_type,
                "filename": filename,
                "sha256": sha256,
                "url": url,
            }
        )

    manifest = {
        "$schema": "https://github.com/Navin45/bytebuddhi/raw/main/schemas/release.schema.json",
        "version": args.version,
        "release_date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": args.commit,
        "channel": args.channel,
        "protocol_version": args.protocol_version,
        "minimum_python_version": args.min_python,
        "supported_platforms": ["windows-x64", "macos-arm64", "macos-x64", "linux-x64"],
        "artifacts": artifacts,
        "update_channels": ["stable", "beta"],
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
