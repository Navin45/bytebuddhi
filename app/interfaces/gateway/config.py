"""Single resolution path for gateway URL, bind address, and execution mode.

Precedence for the endpoint:

    explicit argument
        > BYTEBUDDHI_GATEWAY_URL
        > BYTEBUDDHI_API_URL
        > local gateway default (http://127.0.0.1:<port>)

``login --api-url`` is the explicit argument for authentication commands.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.interfaces.gateway.errors import GatewayConfigError

GATEWAY_URL_ENV = "BYTEBUDDHI_GATEWAY_URL"
API_URL_ENV = "BYTEBUDDHI_API_URL"
HOST_ENV = "BYTEBUDDHI_GATEWAY_HOST"
PORT_ENV = "BYTEBUDDHI_GATEWAY_PORT"
EXECUTION_MODE_ENV = "BYTEBUDDHI_EXECUTION_MODE"
CONFIG_DIR_ENV = "BYTEBUDDHI_CONFIG_DIR"
START_TIMEOUT_ENV = "BYTEBUDDHI_GATEWAY_START_TIMEOUT"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_START_TIMEOUT_SECONDS = 30.0
MAX_START_TIMEOUT_SECONDS = 120.0

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_WILDCARD_HOSTS = frozenset({"0.0.0.0", "::"})


@dataclass(frozen=True)
class BindAddress:
    """Local gateway listen address and the URL clients on this machine use."""

    host: str
    port: int
    url: str
    exposed: bool


@dataclass(frozen=True)
class GatewayEndpoint:
    """Resolved gateway origin. ``local`` is the managed loopback gateway."""

    url: str
    source: str
    local: bool


def config_dir() -> Path:
    """ByteBuddhi per-user directory. Not the repository tree."""
    override = (os.environ.get(CONFIG_DIR_ENV) or "").strip()
    if override:
        return Path(override)
    return Path.home() / ".bytebuddhi"


def resolve_execution_mode(
    *, embedded_flag: bool, gateway_flag: bool = False, environ: Mapping[str, str] | None = None
) -> str:
    """Return ``gateway`` (default) or ``embedded``.

    ``--embedded`` and ``--gateway`` win over ``BYTEBUDDHI_EXECUTION_MODE``.
    An unavailable gateway never selects embedded mode.
    """
    if embedded_flag and gateway_flag:
        raise GatewayConfigError("Pass only one of --embedded or --gateway", usage=True)
    if embedded_flag:
        return "embedded"
    if gateway_flag:
        return "gateway"
    env = environ if environ is not None else os.environ
    raw = (env.get(EXECUTION_MODE_ENV) or "").strip().lower()
    if not raw:
        return "gateway"
    if raw not in {"gateway", "embedded"}:
        raise GatewayConfigError(
            f"{EXECUTION_MODE_ENV} must be 'gateway' or 'embedded'",
            usage=False,
        )
    return raw


def resolve_bind_address(
    host: str | None,
    port: int | str | None,
    environ: Mapping[str, str] | None = None,
) -> BindAddress:
    """Resolve the local gateway bind address. Loopback unless explicitly overridden."""
    env = environ if environ is not None else os.environ
    env_host = env.get(HOST_ENV)
    env_port = env.get(PORT_ENV)
    if host is not None:
        chosen_host = host.strip()
    elif env_host is not None and env_host.strip():
        chosen_host = env_host.strip()
    else:
        chosen_host = DEFAULT_HOST
    if port is not None:
        chosen_port = _parse_port(port, usage=host is not None or port is not None)
    elif env_port is not None and str(env_port).strip():
        chosen_port = _parse_port(env_port, usage=False)
    else:
        chosen_port = DEFAULT_PORT

    if not chosen_host or "://" in chosen_host or "/" in chosen_host or any(ch.isspace() for ch in chosen_host):
        raise GatewayConfigError("Gateway host is invalid", usage=host is not None)
    if chosen_host in _WILDCARD_HOSTS and host is None and not (env_host and env_host.strip()):
        chosen_host = DEFAULT_HOST

    exposed = chosen_host not in _LOOPBACK_HOSTS
    connect_host = "127.0.0.1" if chosen_host in _WILDCARD_HOSTS else chosen_host
    url = _origin("http", connect_host, chosen_port)
    return BindAddress(host=chosen_host, port=chosen_port, url=url, exposed=exposed)


def resolve_gateway_endpoint(
    explicit_url: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> GatewayEndpoint:
    """Resolve the gateway origin using the documented precedence."""
    env = environ if environ is not None else os.environ
    bind = resolve_bind_address(None, None, env)
    explicit = (explicit_url or "").strip()
    gateway_env = (env.get(GATEWAY_URL_ENV) or "").strip()
    api_env = (env.get(API_URL_ENV) or "").strip()
    if explicit:
        url = normalize_gateway_url(explicit, usage=True)
        source = "explicit"
    elif gateway_env:
        url = normalize_gateway_url(gateway_env, usage=False)
        source = GATEWAY_URL_ENV
    elif api_env:
        url = normalize_gateway_url(api_env, usage=False)
        source = API_URL_ENV
    else:
        url = bind.url
        source = "default"
    return GatewayEndpoint(url=url, source=source, local=is_local_gateway(url, bind))


def is_local_gateway(url: str, bind: BindAddress | None = None) -> bool:
    """True when ``url`` is the managed loopback gateway, not merely any local process."""
    target = bind if bind is not None else resolve_bind_address(None, None)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "http" or host not in _LOOPBACK_HOSTS:
        return False
    port = parsed.port or 80
    return port == target.port and not parsed.path.rstrip("/")


def normalize_gateway_url(raw: str, *, usage: bool) -> str:
    """Return an origin without credentials, query, fragment, or path."""
    value = raw.strip()
    if not value or any(ch.isspace() for ch in value):
        raise GatewayConfigError("Gateway URL must be an http(s) origin", usage=usage)
    parsed = urlparse(value)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.netloc:
        raise GatewayConfigError("Gateway URL must be an http(s) origin", usage=usage)
    if parsed.username or parsed.password:
        raise GatewayConfigError("Gateway URL must not include credentials", usage=usage)
    if parsed.query or parsed.fragment:
        raise GatewayConfigError("Gateway URL must not include a query or fragment", usage=usage)
    if parsed.path not in {"", "/"}:
        raise GatewayConfigError(
            "Gateway URL must be an origin without a path, for example http://127.0.0.1:8765",
            usage=usage,
        )
    host = parsed.hostname
    if host is None:
        raise GatewayConfigError("Gateway URL must include a host", usage=usage)
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    return _origin(scheme, host, port)


def start_timeout_seconds(environ: Mapping[str, str] | None = None) -> float:
    """Bounded wait for readiness. Never infinite."""
    env = environ if environ is not None else os.environ
    raw = (env.get(START_TIMEOUT_ENV) or "").strip()
    if not raw:
        return DEFAULT_START_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError as exc:
        raise GatewayConfigError(f"{START_TIMEOUT_ENV} must be a number of seconds", usage=False) from exc
    if value <= 0 or value > MAX_START_TIMEOUT_SECONDS:
        raise GatewayConfigError(
            f"{START_TIMEOUT_ENV} must be between 0 and {MAX_START_TIMEOUT_SECONDS:g} seconds",
            usage=False,
        )
    return value


def _parse_port(value: int | str, *, usage: bool) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise GatewayConfigError("Gateway port must be an integer from 1 to 65535", usage=usage) from exc
    if port < 1 or port > 65535:
        raise GatewayConfigError("Gateway port must be an integer from 1 to 65535", usage=usage)
    return port


def _origin(scheme: str, host: str, port: int) -> str:
    if ":" in host and not host.startswith("["):
        return f"{scheme}://[{host}]:{port}"
    return f"{scheme}://{host}:{port}"
