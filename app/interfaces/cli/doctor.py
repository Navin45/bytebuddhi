"""Operational diagnostics and support bundle generator for ByteBuddhi."""

from __future__ import annotations

import json
import os
import platform
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, TextIO

import httpx

from app._version import MIN_PROTOCOL_VERSION, PROTOCOL_VERSION
from app.infrastructure.config.local_config import load_local_config
from app.interfaces.cli.credentials import CredentialStore
from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.cli.managed_install import _base_dir
from app.interfaces.cli.parser import package_version
from app.interfaces.cli.render import write_json
from app.interfaces.gateway.config import config_dir, resolve_gateway_endpoint

_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-+/=]+")
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
_KEY_RE = re.compile(r"(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z\-_]{35})")
_PASS_RE = re.compile(r"(?i)\b(password|passwd|secret)\s*[:=]\s*([\"'][^\"']+[\"']|[^\s,]+)")
_PROMPT_RE = re.compile(r"(?i)\b(prompt|user_prompt|user_input)\s*[:=]\s*([\"'][^\"']+[\"']|[^\r\n,]+)")
_SECRET_WORDS = {"token", "secret", "password", "passwd", "key", "credential", "auth", "bearer", "prompt"}


def sanitize_text(text: str) -> str:
    """Deterministically scrub auth tokens, JWTs, API keys, passwords, and prompt contents from text."""
    redacted = _BEARER_RE.sub("Bearer [REDACTED]", text)
    redacted = _JWT_RE.sub("[REDACTED_JWT]", redacted)
    redacted = _KEY_RE.sub("[REDACTED_KEY]", redacted)
    redacted = _PASS_RE.sub(r"\1=[REDACTED_PASSWORD]", redacted)
    redacted = _PROMPT_RE.sub(r"\1=[REDACTED_PROMPT]", redacted)
    return redacted


def sanitize_env(env: dict[str, str]) -> dict[str, str]:
    """Sanitize environment variables, masking any value whose key looks sensitive."""
    sanitized: dict[str, str] = {}
    for k, v in env.items():
        k_lower = k.lower()
        if any(w in k_lower for w in _SECRET_WORDS):
            sanitized[k] = "[REDACTED]"
        else:
            sanitized[k] = sanitize_text(v)
    return sanitized


def _profile_diagnostics() -> dict[str, str]:
    from app.infrastructure.config.profile import describe_profile, sqlite_database_path
    from app.infrastructure.persistence.sqlite.database import integrity_report

    described = describe_profile()
    if described["profile"] == "standalone":
        described["sqlite_integrity"] = integrity_report(sqlite_database_path())
    return described


def detect_desktop_installation() -> dict[str, Any]:
    """Check for ByteBuddhi desktop installation."""
    candidates: list[Path] = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / "Programs" / "bytebuddhi-desktop")
            candidates.append(Path(local) / "Programs" / "ByteBuddhi")
        prog = os.environ.get("PROGRAMFILES")
        if prog:
            candidates.append(Path(prog) / "ByteBuddhi")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/ByteBuddhi.app"))
        candidates.append(Path.home() / "Applications" / "ByteBuddhi.app")
    else:
        candidates.append(Path("/usr/share/bytebuddhi-desktop"))
        candidates.append(Path("/usr/bin/bytebuddhi-desktop"))
        candidates.append(Path.home() / ".local" / "share" / "bytebuddhi-desktop")

    for path in candidates:
        if path.exists():
            return {"installed": True, "path": str(path)}

    repo_desktop = Path("desktop/package.json")
    if repo_desktop.is_file():
        try:
            data = json.loads(repo_desktop.read_text(encoding="utf-8"))
            return {
                "installed": True,
                "path": str(repo_desktop.resolve().parent),
                "version": str(data.get("version") or ""),
                "development": True,
            }
        except Exception:
            pass

    return {"installed": False, "path": None}


async def run_diagnostics(gateway_url: str | None = None) -> dict[str, Any]:
    """Collect system, runtime, configuration, and connectivity diagnostics."""
    endpoint = resolve_gateway_endpoint(gateway_url)
    config = load_local_config()
    store = CredentialStore()
    has_credentials = store.load() is not None

    diag: dict[str, Any] = {
        "version": {
            "application": package_version(),
            "protocol": PROTOCOL_VERSION,
            "min_protocol": MIN_PROTOCOL_VERSION,
        },
        "platform": {
            "os": sys.platform,
            "machine": platform.machine(),
            "platform_string": platform.platform(),
            "python_version": platform.python_version(),
            "python_executable": sys.executable,
        },
        "runtime_installation": {
            "managed_install_dir": str(_base_dir()),
            "is_managed": (str(_base_dir()).lower() in sys.executable.lower()),
        },
        "configuration": {
            "location": str(config_dir()),
            "config_version": config.config_version,
            "update_channel": config.channel,
            "theme": config.theme,
            "auto_start_gateway": config.auto_start_gateway,
            **_profile_diagnostics(),
        },
        "authentication": {
            "authenticated": has_credentials,
            "backend": store.backend_name(),
        },
        "desktop": detect_desktop_installation(),
    }

    # Gateway probe
    gateway_info: dict[str, Any] = {
        "url": endpoint.url,
        "is_local": endpoint.local,
        "live": False,
        "ready": False,
        "service": None,
        "reported_version": None,
        "reported_protocol": None,
        "checks": {},
    }

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            live_resp = await client.get(f"{endpoint.url}/api/v1/health/live")
            if live_resp.status_code == 200:
                gateway_info["live"] = True
                data = live_resp.json()
                gateway_info["service"] = data.get("service")
                gateway_info["reported_version"] = data.get("version")
                gateway_info["reported_protocol"] = data.get("protocol_version")

            ready_resp = await client.get(f"{endpoint.url}/api/v1/health/ready")
            if ready_resp.status_code in {200, 503}:
                data = ready_resp.json()
                gateway_info["ready"] = ready_resp.status_code == 200
                gateway_info["checks"] = data.get("checks", {})
    except Exception as exc:
        gateway_info["error"] = sanitize_text(str(exc))

    diag["gateway"] = gateway_info
    return diag


def export_support_bundle(diag: dict[str, Any], zip_path: Path) -> Path:
    """Create a sanitized diagnostic bundle zip file."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. diagnostics.json
        zf.writestr("diagnostics.json", json.dumps(diag, indent=2))

        # 2. config_metadata.json (schema without secrets)
        config_path = config_dir() / "config.json"
        if config_path.is_file():
            try:
                raw_cfg = json.loads(config_path.read_text(encoding="utf-8"))
                safe_cfg = {
                    k: ("[REDACTED]" if any(w in k.lower() for w in _SECRET_WORDS) else v) for k, v in raw_cfg.items()
                }
                zf.writestr("config_metadata.json", json.dumps(safe_cfg, indent=2))
            except Exception:
                pass

        # 3. gateway_sanitized.log
        log_file = config_dir() / "gateway.log"
        if log_file.is_file():
            try:
                log_text = log_file.read_text(encoding="utf-8", errors="replace")
                zf.writestr("gateway_sanitized.log", sanitize_text(log_text))
            except Exception:
                pass

        # 4. system_env.json (masked keys)
        safe_env = sanitize_env(dict(os.environ))
        zf.writestr("system_env.json", json.dumps(safe_env, indent=2))

    return zip_path


def render_human_doctor(diag: dict[str, Any], stream: TextIO) -> None:
    v = diag["version"]
    p = diag["platform"]
    r = diag["runtime_installation"]
    c = diag["configuration"]
    a = diag["authentication"]
    g = diag["gateway"]
    d = diag["desktop"]

    stream.write("ByteBuddhi Operational Diagnostics\n")
    stream.write("===================================\n\n")

    stream.write(f"Version:            {v['application']} (Protocol {v['protocol']})\n")
    stream.write(f"Platform:           {p['platform_string']} ({p['machine']})\n")
    stream.write(f"Python:             {p['python_version']} ({p['python_executable']})\n")
    stream.write(f"Installation:       {r['managed_install_dir']} (managed: {'yes' if r['is_managed'] else 'no'})\n")
    stream.write(
        f"Config Directory:   {c['location']} (schema v{c['config_version']}, channel: {c['update_channel']})\n"
    )
    if c.get("profile"):
        stream.write(f"Profile:            {c['profile']} ({c.get('storage')})\n")
        if c.get("database_path"):
            stream.write(f"Database:           {c['database_path']}\n")
        stream.write(f"Redis:              {c.get('redis')}\n")
        stream.write(f"Execution:          {c.get('execution_mode')}\n")
        if c.get("sqlite_integrity"):
            stream.write(f"SQLite integrity:   {c['sqlite_integrity']}\n")
    stream.write(f"OS Keyring Backend: {a['backend']} (authenticated: {'yes' if a['authenticated'] else 'no'})\n")

    stream.write(f"Desktop App:        {'installed' if d['installed'] else 'not detected'}")
    if d.get("path"):
        stream.write(f" ({d['path']})")
    stream.write("\n\n")

    stream.write("Gateway Status:\n")
    stream.write(f"  URL:              {g['url']}\n")
    stream.write(f"  Live:             {'yes' if g['live'] else 'no'}\n")
    stream.write(f"  Ready:            {'yes' if g['ready'] else 'no'}\n")
    if g.get("reported_version"):
        stream.write(f"  Version:          {g['reported_version']} (protocol {g.get('reported_protocol')})\n")
    if g.get("checks"):
        stream.write("  Health Checks:\n")
        for check, state in g["checks"].items():
            stream.write(f"    - {check}: {state}\n")
    if g.get("error"):
        stream.write(f"  Notice:           {g['error']}\n")
    stream.write("\n")


async def handle_doctor(
    *,
    json_mode: bool,
    export_path: str | None = None,
    gateway_url: str | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    diag = await run_diagnostics(gateway_url)

    if export_path:
        out_path = Path(export_path)
        export_support_bundle(diag, out_path)
        if json_mode:
            write_json({"status": "exported", "bundle": str(out_path.resolve())}, stream=stdout)
        else:
            stdout.write(f"Exported sanitized support bundle to: {out_path.resolve()}\n")
        return int(ExitCode.SUCCESS)

    if json_mode:
        write_json(diag, stream=stdout)
    else:
        render_human_doctor(diag, stdout)

    return int(ExitCode.SUCCESS)
