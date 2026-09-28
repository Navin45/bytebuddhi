#!/usr/bin/env python3
"""Generate a CycloneDX SBOM from locked dependency files.

Produces a minimal CycloneDX 1.5 JSON SBOM from:
  - uv.lock (Python)
  - desktop/pnpm-lock.yaml (Node)

Usage
-----
    python scripts/generate_sbom.py --version 0.1.4 --output sbom.cdx.json
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def parse_uv_lock() -> list[dict]:
    """Extract package name + version from uv.lock."""
    lock_file = ROOT / "uv.lock"
    if not lock_file.exists():
        return []

    components: list[dict] = []
    text = lock_file.read_text(encoding="utf-8")
    # uv.lock uses TOML-ish [[package]] blocks with name/version keys
    current_name = ""
    current_version = ""
    for line in text.splitlines():
        if line.strip() == "[[package]]":
            if current_name and current_version:
                components.append(
                    {
                        "type": "library",
                        "group": "pypi",
                        "name": current_name,
                        "version": current_version,
                        "purl": f"pkg:pypi/{current_name}@{current_version}",
                    }
                )
            current_name = ""
            current_version = ""
        m = re.match(r'^name\s*=\s*"([^"]+)"', line)
        if m:
            current_name = m.group(1)
        m = re.match(r'^version\s*=\s*"([^"]+)"', line)
        if m:
            current_version = m.group(1)
    if current_name and current_version:
        components.append(
            {
                "type": "library",
                "group": "pypi",
                "name": current_name,
                "version": current_version,
                "purl": f"pkg:pypi/{current_name}@{current_version}",
            }
        )
    return components


def parse_pnpm_lock() -> list[dict]:
    """Extract package names + versions from pnpm-lock.yaml (simplified)."""
    lock_file = ROOT / "desktop" / "pnpm-lock.yaml"
    if not lock_file.exists():
        return []

    components: list[dict] = []
    text = lock_file.read_text(encoding="utf-8")
    # Match lines like:   /@scope/name@version: or   /name@version:
    # pnpm v9 lockfile uses entries like: 'package@version':
    seen: set[str] = set()
    for m in re.finditer(r"'?/?(@?[^@\s']+)@(\d+[^:'\"]*)'?:", text):
        name = m.group(1)
        version = m.group(2)
        key = f"{name}@{version}"
        if key not in seen:
            seen.add(key)
            components.append(
                {
                    "type": "library",
                    "group": "npm",
                    "name": name,
                    "version": version,
                    "purl": f"pkg:npm/{name}@{version}",
                }
            )
    return components


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate CycloneDX SBOM")
    parser.add_argument("--version", required=True, help="Application version")
    parser.add_argument("--output", default="sbom.cdx.json", help="Output path")
    args = parser.parse_args()

    python_deps = parse_uv_lock()
    node_deps = parse_pnpm_lock()

    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:bytebuddhi-{args.version}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "tools": [{"vendor": "ByteBuddhi", "name": "generate_sbom.py", "version": "1.0.0"}],
            "component": {
                "type": "application",
                "name": "bytebuddhi",
                "version": args.version,
                "purl": f"pkg:pypi/bytebuddhi@{args.version}",
            },
        },
        "components": python_deps + node_deps,
    }

    output = Path(args.output)
    output.write_text(json.dumps(sbom, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output} ({len(python_deps)} Python + {len(node_deps)} Node components)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
