"""Managed CLI installation layout and operations.

This module implements a versioned, immutable installation directory so that
``bytebuddhi update`` and ``bytebuddhi update --rollback`` are safe and atomic.

Layout
------
Unix: ``~/.bytebuddhi/``
Windows: ``%LOCALAPPDATA%\\ByteBuddhi\\``

::

    installs/
        0.1.3/          ← venv with the wheel installed
        0.1.4/
    bin/
        bytebuddhi      ← launcher shim
    current              ← text file containing the active version string
    state/
    logs/
    cache/
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from app._version import DEFAULT_CHANNEL, GITHUB_OWNER, GITHUB_REPO

# ── Directory layout ─────────────────────────────────────────────────


def _base_dir() -> Path:
    """Platform-correct managed-install root."""
    env = os.environ.get("BYTEBUDDHI_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "ByteBuddhi"
        return Path.home() / "AppData" / "Local" / "ByteBuddhi"
    return Path.home() / ".bytebuddhi"


@dataclass(frozen=True)
class ManagedLayout:
    root: Path

    @property
    def installs_dir(self) -> Path:
        return self.root / "installs"

    @property
    def bin_dir(self) -> Path:
        return self.root / "bin"

    @property
    def current_file(self) -> Path:
        return self.root / "current"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    def ensure_dirs(self) -> None:
        for d in (self.installs_dir, self.bin_dir, self.state_dir, self.logs_dir, self.cache_dir):
            d.mkdir(parents=True, exist_ok=True)

    def version_dir(self, version: str) -> Path:
        return self.installs_dir / version

    def active_version(self) -> str | None:
        if not self.current_file.exists():
            return None
        return self.current_file.read_text(encoding="utf-8").strip() or None

    def activate(self, version: str) -> None:
        self.current_file.write_text(version + "\n", encoding="utf-8")

    def installed_versions(self) -> list[str]:
        if not self.installs_dir.exists():
            return []
        return sorted(
            [d.name for d in self.installs_dir.iterdir() if d.is_dir()],
            key=_semver_key,
        )

    def previous_version(self) -> str | None:
        current = self.active_version()
        versions = self.installed_versions()
        if not current or current not in versions:
            return versions[-1] if versions else None
        idx = versions.index(current)
        return versions[idx - 1] if idx > 0 else None


def default_layout() -> ManagedLayout:
    return ManagedLayout(root=_base_dir())


# ── Release manifest ─────────────────────────────────────────────────

RELEASE_JSON_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest/download/release.json"
_GITHUB_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases?per_page=20"
_UPDATER_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "bytebuddhi-updater",
}


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    python_wheel_url: str
    python_wheel_sha256: str
    release_date: str
    channel: str = DEFAULT_CHANNEL
    protocol_version: int = 1


def _read_json(url: str) -> object:
    req = Request(url, headers=_UPDATER_HEADERS)
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _is_prerelease_version(version: str) -> bool:
    return "-" in version.split("+", 1)[0]


def release_is_eligible(channel: str, release: ReleaseInfo) -> bool:
    """Stable installs accept only a stable manifest. Beta may accept an RC."""
    return channel != "stable" or (not _is_prerelease_version(release.version) and release.channel == "stable")


def release_info_from_manifest(data: object, channel: str = DEFAULT_CHANNEL) -> ReleaseInfo:
    """Parse a release manifest and reject a malformed or ineligible document."""
    if channel not in {"stable", "beta"}:
        raise RuntimeError(f"Unknown update channel: {channel}")
    if not isinstance(data, dict):
        raise RuntimeError("release manifest is not a JSON object")
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError("release manifest is missing version")
    manifest_channel = data.get("channel", DEFAULT_CHANNEL)
    if manifest_channel not in {"stable", "beta"}:
        raise RuntimeError(f"release manifest has an unknown channel: {manifest_channel}")
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise RuntimeError("release manifest is missing artifacts")
    cli_artifact = next(
        (art for art in artifacts if isinstance(art, dict) and art.get("type") == "python_wheel"),
        None,
    )
    if not isinstance(cli_artifact, dict):
        raise RuntimeError("release.json does not contain a python_wheel artifact")
    url = cli_artifact.get("url")
    sha256 = cli_artifact.get("sha256")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise RuntimeError("release manifest wheel URL is missing or not https")
    if not isinstance(sha256, str) or len(sha256) != 64 or any(char not in "0123456789abcdefABCDEF" for char in sha256):
        raise RuntimeError("release manifest wheel checksum is malformed")
    protocol = data.get("protocol_version", 1)
    if not isinstance(protocol, int):
        raise RuntimeError("release manifest protocol_version is malformed")
    info = ReleaseInfo(
        version=version.strip(),
        python_wheel_url=url,
        python_wheel_sha256=sha256.lower(),
        release_date=str(data.get("release_date", "")),
        channel=str(manifest_channel),
        protocol_version=protocol,
    )
    if not release_is_eligible(channel, info):
        raise RuntimeError("stable channel rejected a prerelease manifest")
    return info


def _manifest_url_from_release(release: object) -> str:
    if not isinstance(release, dict) or release.get("draft") is True:
        raise RuntimeError("GitHub release entry is not a published release")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError("GitHub release is missing assets")
    for asset in assets:
        if isinstance(asset, dict) and asset.get("name") == "release.json":
            url = asset.get("browser_download_url")
            if isinstance(url, str) and url.startswith("https://"):
                return url
    raise RuntimeError("Newest release has no release.json asset")


def fetch_release_info(channel: str = DEFAULT_CHANNEL) -> ReleaseInfo:
    """Download the release manifest for one update channel.

    Stable reads GitHub's latest non-prerelease asset. Beta reads the newest
    published release, which may be a release candidate.
    """
    if channel not in {"stable", "beta"}:
        raise RuntimeError(f"Unknown update channel: {channel}")
    if channel == "beta":
        payload = _read_json(_GITHUB_RELEASES_URL)
        if not isinstance(payload, list) or not payload:
            raise RuntimeError("No GitHub releases are available")
        chosen = next((item for item in payload if isinstance(item, dict) and item.get("draft") is not True), None)
        if chosen is None:
            raise RuntimeError("No published GitHub releases are available")
        data = _read_json(_manifest_url_from_release(chosen))
    else:
        data = _read_json(RELEASE_JSON_URL)
    return release_info_from_manifest(data, channel)


# ── Download + verification ──────────────────────────────────────────


def download_and_verify(url: str, expected_sha256: str, dest: Path) -> None:
    """Download *url* to *dest*, verify SHA-256, raise on mismatch."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".partial")
    try:
        req = Request(url)
        sha = hashlib.sha256()
        with urlopen(req, timeout=120) as resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                sha.update(chunk)
        digest = sha.hexdigest()
        if digest != expected_sha256:
            raise RuntimeError(f"SHA-256 mismatch: expected {expected_sha256}, got {digest}")
        tmp.replace(dest)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


# ── Install into versioned venv ──────────────────────────────────────


def install_wheel(layout: ManagedLayout, version: str, wheel_path: Path) -> Path:
    """Create a venv and install the wheel into ``installs/<version>/``."""
    venv_dir = layout.version_dir(version)
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    venv_dir.mkdir(parents=True)

    # Create venv
    subprocess.check_call(
        [sys.executable, "-m", "venv", str(venv_dir)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    # Determine pip/python inside venv
    if sys.platform == "win32":
        venv_python = venv_dir / "Scripts" / "python.exe"
    else:
        venv_python = venv_dir / "bin" / "python"

    # Install wheel
    subprocess.check_call(
        [str(venv_python), "-m", "pip", "install", "--no-deps", str(wheel_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    return venv_dir


def smoke_test(layout: ManagedLayout, version: str) -> bool:
    """Verify the installed version responds to ``--version``."""
    venv_dir = layout.version_dir(version)
    if sys.platform == "win32":
        exe = venv_dir / "Scripts" / "bytebuddhi.exe"
    else:
        exe = venv_dir / "bin" / "bytebuddhi"

    if not exe.exists():
        return False

    try:
        result = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0 and version in result.stdout
    except Exception:
        return False


# ── Launcher / shim ──────────────────────────────────────────────────

_UNIX_SHIM = """\
#!/bin/sh
set -e
BASE_DIR="$(dirname "$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")")"
CURRENT_FILE="$BASE_DIR/current"
if [ ! -f "$CURRENT_FILE" ]; then
  echo "ByteBuddhi is not installed. Run the installer first." >&2
  exit 1
fi
VERSION=$(cat "$CURRENT_FILE" | tr -d '\\n')
VENV="$BASE_DIR/installs/$VERSION"
exec "$VENV/bin/bytebuddhi" "$@"
"""

_WIN_SHIM = """\
@echo off
setlocal enabledelayedexpansion
set "BASE_DIR=%~dp0.."
set /p VERSION=<"%BASE_DIR%\\current"
set "VERSION=!VERSION: =!"
if "!VERSION!"=="" (
    echo ByteBuddhi is not installed. Run the installer first. >&2
    exit /b 1
)
set "EXE=%BASE_DIR%\\installs\\!VERSION!\\Scripts\\bytebuddhi.exe"
if not exist "!EXE!" (
    echo ByteBuddhi !VERSION! is not found. Run bytebuddhi update. >&2
    exit /b 1
)
"!EXE!" %*
"""


def write_launcher(layout: ManagedLayout) -> Path:
    """Write a launcher shim in ``bin/``."""
    layout.bin_dir.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        shim = layout.bin_dir / "bytebuddhi.cmd"
        shim.write_text(_WIN_SHIM, encoding="utf-8")
    else:
        shim = layout.bin_dir / "bytebuddhi"
        shim.write_text(_UNIX_SHIM, encoding="utf-8")
        shim.chmod(0o755)
    return shim


# ── Rollback ─────────────────────────────────────────────────────────


def rollback(layout: ManagedLayout) -> str | None:
    """Switch back to the previous installed version. Returns the version or None."""
    prev = layout.previous_version()
    if not prev:
        return None
    if not layout.version_dir(prev).exists():
        return None
    layout.activate(prev)
    return prev


# ── Uninstall ────────────────────────────────────────────────────────


def uninstall(layout: ManagedLayout, *, purge: bool = False) -> list[str]:
    """Remove installation. Returns list of paths removed.

    Without ``purge``, keeps ``state/`` (config, credentials).
    With ``purge``, removes everything including user data.
    """
    removed: list[str] = []

    for name in ("installs", "bin", "cache", "logs"):
        d = layout.root / name
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            removed.append(str(d))

    current = layout.current_file
    if current.exists():
        current.unlink(missing_ok=True)
        removed.append(str(current))

    if purge:
        state = layout.state_dir
        if state.exists():
            shutil.rmtree(state, ignore_errors=True)
            removed.append(str(state))
        # Remove the root if empty
        if layout.root.exists() and not any(layout.root.iterdir()):
            layout.root.rmdir()
            removed.append(str(layout.root))

    return removed


# ── Helpers ──────────────────────────────────────────────────────────


def _pre_id(part: str) -> tuple[int, int | str]:
    if part.isdigit():
        return (0, int(part))
    return (1, part)


def _semver_key(version_str: str) -> tuple[tuple[int, ...], int, tuple[tuple[int, int | str], ...]]:
    clean = version_str.lstrip("v").strip().split("+", 1)[0]
    if "-" in clean:
        base, prerelease = clean.split("-", 1)
        release_rank = 0
        prerelease_parts = tuple(_pre_id(part) for part in prerelease.split(".") if part)
    else:
        base = clean
        release_rank = 1
        prerelease_parts = ()
    base_parts = []
    for part in base.split("."):
        try:
            base_parts.append(int(part))
        except ValueError:
            base_parts.append(0)
    return (tuple(base_parts), release_rank, prerelease_parts)


def compare_versions(a: str, b: str) -> int:
    """Return -1, 0, or 1 comparing semver strings."""
    ka, kb = _semver_key(a), _semver_key(b)
    if ka < kb:
        return -1
    if ka > kb:
        return 1
    return 0
