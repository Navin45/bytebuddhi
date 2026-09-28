#!/usr/bin/env python3
"""Generate SHA256SUMS for all release artifacts in a directory.

Usage
-----
    python scripts/generate_checksums.py dist/
    python scripts/generate_checksums.py dist/ --output SHA256SUMS
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate SHA-256 checksums")
    parser.add_argument("directory", type=Path, help="Directory containing artifacts")
    parser.add_argument("--output", default="SHA256SUMS", help="Output file path")
    args = parser.parse_args()

    if not args.directory.is_dir():
        print(f"ERROR: {args.directory} is not a directory", file=sys.stderr)
        return 1

    lines: list[str] = []
    for path in sorted(args.directory.iterdir()):
        if path.is_file() and path.name not in {"SHA256SUMS", "release.json"}:
            digest = sha256_file(path)
            lines.append(f"{digest}  {path.name}")
            print(f"  {digest}  {path.name}")

    if not lines:
        print("WARNING: no artifacts found", file=sys.stderr)
        return 1

    output = Path(args.output)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {output} ({len(lines)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
