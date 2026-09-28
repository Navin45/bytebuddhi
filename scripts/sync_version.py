#!/usr/bin/env python3
"""Synchronise the application version across all source-of-truth files.

Usage
-----
    # Read version from pyproject.toml, write to secondary files:
    python scripts/sync_version.py

    # Verify every file agrees with a git tag (CI release guard):
    python scripts/sync_version.py --check-tag v0.1.4

Exit codes
----------
    0  All files are in sync (or have been written).
    1  Version mismatch detected (with --check-tag or --verify-only).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PYPROJECT = ROOT / "pyproject.toml"
VERSION_PY = ROOT / "app" / "_version.py"
INIT_PY = ROOT / "app" / "__init__.py"
DESKTOP_PKG = ROOT / "desktop" / "package.json"
VSCODE_PKG = ROOT / "vscode-extension" / "package.json"

_TOML_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
_PY_VERSION_RE = re.compile(r'^(APP_VERSION\s*=\s*")[^"]+(")$', re.MULTILINE)
_PY_INIT_VERSION_RE = re.compile(r'^(__version__\s*=\s*")[^"]+(")$', re.MULTILINE)


def read_pyproject_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = _TOML_RE.search(text)
    if not match:
        print("ERROR: Could not find version in pyproject.toml", file=sys.stderr)
        sys.exit(1)
    return match.group(1)


def write_pyproject(version: str) -> bool:
    text = PYPROJECT.read_text(encoding="utf-8")
    new_text = _TOML_RE.sub(f'version = "{version}"', text, count=1)
    if new_text == text:
        return True
    PYPROJECT.write_text(new_text, encoding="utf-8")
    print(f"  WRITE {PYPROJECT.relative_to(ROOT)} -> {version}")
    return True


def write_version_py(version: str) -> bool:
    if not VERSION_PY.exists():
        print(f"  SKIP  {VERSION_PY.relative_to(ROOT)} (does not exist)", file=sys.stderr)
        return True
    text = VERSION_PY.read_text(encoding="utf-8")
    new_text = _PY_VERSION_RE.sub(rf"\g<1>{version}\2", text)
    if new_text == text:
        return True  # already correct
    VERSION_PY.write_text(new_text, encoding="utf-8")
    print(f"  WRITE {VERSION_PY.relative_to(ROOT)} -> {version}")
    return True


def write_init_py(version: str) -> bool:
    if not INIT_PY.exists():
        print(f"  SKIP  {INIT_PY.relative_to(ROOT)} (does not exist)", file=sys.stderr)
        return True
    text = INIT_PY.read_text(encoding="utf-8")
    if "from app._version" in text:
        return True  # Re-exported from app/_version.py
    new_text = _PY_INIT_VERSION_RE.sub(rf"\g<1>{version}\2", text)
    if new_text == text:
        return True
    INIT_PY.write_text(new_text, encoding="utf-8")
    print(f"  WRITE {INIT_PY.relative_to(ROOT)} -> {version}")
    return True


def write_desktop_package(version: str) -> bool:
    if not DESKTOP_PKG.exists():
        print(f"  SKIP  {DESKTOP_PKG.relative_to(ROOT)} (does not exist)", file=sys.stderr)
        return True
    data = json.loads(DESKTOP_PKG.read_text(encoding="utf-8"))
    if data.get("version") == version:
        return True
    data["version"] = version
    DESKTOP_PKG.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"  WRITE {DESKTOP_PKG.relative_to(ROOT)} -> {version}")
    return True


def write_vscode_package(version: str) -> bool:
    if not VSCODE_PKG.exists():
        print(f"  SKIP  {VSCODE_PKG.relative_to(ROOT)} (does not exist)", file=sys.stderr)
        return True
    data = json.loads(VSCODE_PKG.read_text(encoding="utf-8"))
    if data.get("version") == version:
        return True
    data["version"] = version
    VSCODE_PKG.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"  WRITE {VSCODE_PKG.relative_to(ROOT)} -> {version}")
    return True


def verify_all(expected: str) -> bool:
    """Return True when every file contains *expected*."""
    ok = True

    # pyproject.toml
    actual = read_pyproject_version()
    if actual != expected:
        print(f"  MISMATCH pyproject.toml: {actual} != {expected}", file=sys.stderr)
        ok = False

    # app/_version.py
    if VERSION_PY.exists():
        match = _PY_VERSION_RE.search(VERSION_PY.read_text(encoding="utf-8"))
        v = match.group(0).split('"')[1] if match else "<missing>"
        if v != expected:
            print(f"  MISMATCH app/_version.py: {v} != {expected}", file=sys.stderr)
            ok = False

    # app/__init__.py
    if INIT_PY.exists():
        text = INIT_PY.read_text(encoding="utf-8")
        if "from app._version import APP_VERSION as __version__" in text:
            # Re-exports from app._version, which is verified above
            pass
        else:
            match = _PY_INIT_VERSION_RE.search(text)
            v = match.group(0).split('"')[1] if match else "<missing>"
            if v != expected:
                print(f"  MISMATCH app/__init__.py: {v} != {expected}", file=sys.stderr)
                ok = False

    # desktop/package.json
    if DESKTOP_PKG.exists():
        data = json.loads(DESKTOP_PKG.read_text(encoding="utf-8"))
        v = data.get("version", "<missing>")
        if v != expected:
            print(f"  MISMATCH desktop/package.json: {v} != {expected}", file=sys.stderr)
            ok = False

    # vscode-extension/package.json
    if VSCODE_PKG.exists():
        data = json.loads(VSCODE_PKG.read_text(encoding="utf-8"))
        v = data.get("version", "<missing>")
        if v != expected:
            print(f"  MISMATCH vscode-extension/package.json: {v} != {expected}", file=sys.stderr)
            ok = False

    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronise ByteBuddhi version fields")
    parser.add_argument(
        "--check-tag",
        metavar="TAG",
        help="Verify all files match the given git tag (e.g. v0.1.4). Fails if any differ.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify consistency; do not write any files.",
    )
    parser.add_argument(
        "new_version",
        nargs="?",
        default=None,
        help="Optional new version string to set across all files (e.g. 0.1.4-rc.1)",
    )
    args = parser.parse_args()

    if args.check_tag:
        tag = args.check_tag
        expected = tag.lstrip("v")
        print(f"Verifying version {expected} (tag {tag})...")
        if not verify_all(expected):
            print("\nRELEASE BLOCKED: version mismatch.", file=sys.stderr)
            return 1
        print("All version fields match.")
        return 0

    if args.new_version:
        target = args.new_version.lstrip("v")
        write_pyproject(target)
        version = target
    else:
        version = read_pyproject_version()
    print(f"Source version: {version}")

    if args.verify_only:
        if not verify_all(version):
            print("\nVersion mismatch detected.", file=sys.stderr)
            return 1
        print("All version fields match.")
        return 0

    write_version_py(version)
    write_init_py(version)
    write_desktop_package(version)
    write_vscode_package(version)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
