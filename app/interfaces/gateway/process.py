"""Cross-platform process and lock helpers. No shell and no Unix-signal assumption."""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path
from typing import Any, BinaryIO, cast


class GatewayLock:
    """Exclusive lock held by the live gateway process.

    A free lock means the recorded PID must not be killed: it is not our child.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: BinaryIO | None = None

    def try_acquire(self) -> bool:
        self.release()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _ensure_lock_byte(self.path)
        handle = open(self.path, "r+b")  # noqa: SIM115 — held until GatewayLock.release
        try:
            _lock(handle, blocking=False)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            _unlock(handle)
        except OSError:
            pass
        finally:
            handle.close()


def process_exists(pid: int) -> bool:
    """Return whether ``pid`` is a live process. Does not signal or terminate it."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_process_exists(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def request_terminate_signal(pid: int) -> None:
    """Ask a POSIX process to exit. Windows uses the shutdown file instead."""
    if sys.platform == "win32" or pid <= 0 or pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return


def terminate_process(pid: int) -> None:
    """Last-resort termination of one PID. Never targets the current process."""
    if pid <= 0 or pid == os.getpid():
        return
    if sys.platform == "win32":
        _windows_terminate(pid)
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return


def port_is_open(host: str, port: int, *, timeout: float = 0.4) -> bool:
    import socket

    connect_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    try:
        with socket.create_connection((connect_host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ensure_lock_byte(path: Path) -> None:
    if path.exists() and path.stat().st_size >= 1:
        return
    with open(path, "ab") as handle:
        handle.write(b"\0")
        handle.flush()


def _lock(handle: BinaryIO, *, blocking: bool) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
        msvcrt.locking(handle.fileno(), mode, 1)
        return
    import fcntl

    flags = fcntl.LOCK_EX
    if not blocking:
        flags |= fcntl.LOCK_NB
    fcntl.flock(handle.fileno(), flags)


def _unlock(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _windows_process_exists(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel = cast(Any, ctypes).WinDLL("kernel32", use_last_error=True)
    process_query = 0x1000
    still_active = 259
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(process_query, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return int(code.value) == still_active
    finally:
        kernel.CloseHandle(handle)


def _windows_terminate(pid: int) -> None:
    import ctypes
    from ctypes import wintypes

    process_terminate = 0x0001
    kernel = cast(Any, ctypes).WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(process_terminate, False, pid)
    if not handle:
        return
    try:
        kernel.TerminateProcess(handle, 1)
    finally:
        kernel.CloseHandle(handle)
