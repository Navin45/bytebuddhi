"""Run the existing FastAPI application as a single-process local gateway."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from app import __version__
from app.interfaces.gateway.config import config_dir, resolve_bind_address
from app.interfaces.gateway.errors import GatewayConfigError
from app.interfaces.gateway.process import GatewayLock
from app.interfaces.gateway.state import (
    GatewayState,
    clear_shutdown,
    lock_path,
    save_state,
    shutdown_path,
    utc_now,
)

_HELD_LOCK: GatewayLock | None = None


def gateway_server_command(host: str, port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "app.interfaces.gateway.server",
        "--host",
        host,
        "--port",
        str(port),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bytebuddhi-gateway")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return run_server(host=args.host, port=args.port)
    except GatewayConfigError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 2 if exc.usage else 6


def run_server(*, host: str | None, port: int | None) -> int:
    """Foreground gateway. Uses the existing FastAPI app, lifespan, and routes."""
    bind = resolve_bind_address(host, port)
    if bind.exposed:
        print(
            f"warning: gateway bind {bind.host} is not loopback. "
            "Local gateways should stay on 127.0.0.1 unless you explicitly need another interface.",
            file=sys.stderr,
        )
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    lock = _acquire_with_retry(lock_path(directory))
    if lock is None:
        print(
            f"error: a ByteBuddhi gateway is already running for {directory}",
            file=sys.stderr,
        )
        return 1
    global _HELD_LOCK
    _HELD_LOCK = lock
    clear_shutdown(directory)
    save_state(
        directory,
        GatewayState(
            pid=os.getpid(),
            bind_host=bind.host,
            port=bind.port,
            url=bind.url,
            started_at=utc_now(),
            version=__version__,
        ),
    )
    try:
        asyncio.run(_serve(bind.host, bind.port, directory))
    except KeyboardInterrupt:
        return 0
    return 0


async def _serve(host: str, port: int, directory: Path) -> None:
    import uvicorn

    shutdown_file = shutdown_path(directory)
    config = uvicorn.Config(
        "app.interfaces.api.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
        timeout_graceful_shutdown=30,
        proxy_headers=False,
        server_header=False,
    )
    server = uvicorn.Server(config)

    async def _watch() -> None:
        while not server.should_exit:
            if shutdown_file.is_file():
                server.should_exit = True
                return
            await asyncio.sleep(0.25)

    watcher = asyncio.create_task(_watch())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher


def _acquire_with_retry(path: Path) -> GatewayLock | None:
    """Retry briefly so a parent status check cannot steal startup."""
    deadline = time.monotonic() + 5.0
    while True:
        lock = GatewayLock(path)
        if lock.try_acquire():
            return lock
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.05)


if __name__ == "__main__":
    raise SystemExit(main())
