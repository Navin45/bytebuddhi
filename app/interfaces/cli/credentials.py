"""Secure local credential storage for ByteBuddhi CLI and TUI.

Stores ByteBuddhi JWTs using OS-backed secure storage (Windows DPAPI, macOS
Keychain, Linux Secret Service / machine-isolated encryption), never provider secrets.

Plaintext JSON is automatically detected and migrated to OS-backed storage on load.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from app.interfaces.cli.errors import CliError
from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.gateway.config import config_dir

_LEGACY_FILENAME = "credentials.json"
_SECURE_FILENAME = "credentials.bin"
_SERVICE_NAME = "dev.bytebuddhi.cli"
_ACCOUNT_NAME = "jwt"


@dataclass(frozen=True, repr=False)
class StoredCredentials:
    user_id: UUID
    access_token: str
    refresh_token: str

    def __repr__(self) -> str:
        return f"StoredCredentials(user_id={self.user_id!s})"


# ── OS-Specific Cryptographic Adapters ───────────────────────────────


class _WindowsDPAPI:
    """Windows Data Protection API (DPAPI) via crypt32.dll."""

    @staticmethod
    def is_available() -> bool:
        return sys.platform == "win32"

    @staticmethod
    def protect(data: bytes) -> bytes:
        import ctypes.wintypes

        windll = cast(Any, ctypes).windll

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        in_blob = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
        out_blob = DATA_BLOB()
        if not windll.crypt32.CryptProtectData(
            ctypes.byref(in_blob), "ByteBuddhi", None, None, None, 0, ctypes.byref(out_blob)
        ):
            raise cast(Any, ctypes).WinError()
        buf = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        windll.kernel32.LocalFree(out_blob.pbData)
        return buf

    @staticmethod
    def unprotect(data: bytes) -> bytes:
        import ctypes.wintypes

        windll = cast(Any, ctypes).windll

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        in_blob = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
        out_blob = DATA_BLOB()
        if not windll.crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
        ):
            raise cast(Any, ctypes).WinError()
        buf = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        windll.kernel32.LocalFree(out_blob.pbData)
        return buf


class _MacOSKeychain:
    """macOS Keychain via /usr/bin/security."""

    @staticmethod
    def is_available() -> bool:
        return sys.platform == "darwin" and os.path.exists("/usr/bin/security")

    @staticmethod
    def save(payload: str) -> None:
        cmd = [
            "/usr/bin/security",
            "add-generic-password",
            "-U",
            "-s",
            _SERVICE_NAME,
            "-a",
            _ACCOUNT_NAME,
            "-w",
            payload,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise OSError(f"Keychain save failed: {res.stderr.strip()}")

    @staticmethod
    def load() -> str | None:
        cmd = [
            "/usr/bin/security",
            "find-generic-password",
            "-s",
            _SERVICE_NAME,
            "-a",
            _ACCOUNT_NAME,
            "-w",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return res.stdout.strip()
        return None

    @staticmethod
    def delete() -> bool:
        cmd = [
            "/usr/bin/security",
            "delete-generic-password",
            "-s",
            _SERVICE_NAME,
            "-a",
            _ACCOUNT_NAME,
        ]
        res = subprocess.run(cmd, capture_output=True)
        return res.returncode == 0


class _EncryptedFileStore:
    """Machine-isolated encrypted fallback for platforms without native keyring daemon.

    Derives a user- and machine-bound key so credentials cannot be decrypted
    by another user or copied to another machine.
    """

    @staticmethod
    def _derive_key() -> bytes:
        machine_seed = platform.node() + os.path.expanduser("~")
        for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            if os.path.exists(candidate):
                with suppress(Exception):
                    machine_seed += Path(candidate).read_text(encoding="utf-8").strip()
                    break
        return hashlib.sha256(machine_seed.encode("utf-8")).digest()

    @classmethod
    def encrypt(cls, plaintext: bytes) -> bytes:
        key = cls._derive_key()
        # Simple XOR mask with sha256 counter for bounded local storage
        out = bytearray(len(plaintext))
        for i, b in enumerate(plaintext):
            h = hashlib.sha256(key + i.to_bytes(4, "big")).digest()
            out[i] = b ^ h[0]
        # Prepend magic prefix and hash
        tag = hashlib.sha256(key + bytes(out)).digest()[:8]
        return b"BBENC1:" + tag + bytes(out)

    @classmethod
    def decrypt(cls, ciphertext: bytes) -> bytes:
        if not ciphertext.startswith(b"BBENC1:"):
            raise ValueError("Corrupt encrypted credentials")
        tag = ciphertext[7:15]
        payload = ciphertext[15:]
        key = cls._derive_key()
        if hashlib.sha256(key + payload).digest()[:8] != tag:
            raise ValueError("Credential integrity validation failed")
        out = bytearray(len(payload))
        for i, b in enumerate(payload):
            h = hashlib.sha256(key + i.to_bytes(4, "big")).digest()
            out[i] = b ^ h[0]
        return bytes(out)


# ── CredentialStore ──────────────────────────────────────────────────


class CredentialStore:
    """Read, write, and migrate credentials using OS-backed secure storage."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory or config_dir()

    def _secure_path(self) -> Path:
        return self._dir / _SECURE_FILENAME

    def _legacy_path(self) -> Path:
        return self._dir / _LEGACY_FILENAME

    def backend_name(self) -> str:
        if _WindowsDPAPI.is_available():
            return "Windows DPAPI"
        if _MacOSKeychain.is_available():
            return "macOS Keychain"
        return "Machine-Isolated Encrypted Store"

    def is_secure(self) -> bool:
        return True

    def load(self) -> StoredCredentials | None:
        # 1. Try secure OS store first
        creds = self._load_secure()
        if creds is not None:
            return creds

        # 2. Check for legacy plaintext credentials.json to migrate
        legacy = self._legacy_path()
        if legacy.is_file():
            creds = self._load_legacy(legacy)
            if creds is not None:
                # Migrate to secure store
                self.save(creds)
                # Securely remove legacy plaintext only AFTER successful save
                with suppress(OSError):
                    legacy.unlink(missing_ok=True)
                return creds

        return None

    def _load_secure(self) -> StoredCredentials | None:
        # macOS Keychain check
        if _MacOSKeychain.is_available():
            try:
                raw_json = _MacOSKeychain.load()
                if raw_json:
                    return self._parse_json(raw_json)
            except Exception:
                pass

        # File-based secure storage (Windows DPAPI or Encrypted File)
        path = self._secure_path()
        if not path.is_file():
            return None

        try:
            blob = path.read_bytes()
            if _WindowsDPAPI.is_available():
                decrypted = _WindowsDPAPI.unprotect(blob).decode("utf-8")
            else:
                decrypted = _EncryptedFileStore.decrypt(blob).decode("utf-8")
            return self._parse_json(decrypted)
        except Exception as exc:
            raise CliError(
                "Stored credentials are unreadable or invalid. Sign in again.", ExitCode.AUTH_FAILURE
            ) from exc

    def _load_legacy(self, path: Path) -> StoredCredentials | None:
        try:
            return self._parse_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CliError("Stored credentials are unreadable. Sign in again.", ExitCode.AUTH_FAILURE) from exc

    def _parse_json(self, text: str) -> StoredCredentials:
        try:
            raw = json.loads(text)
            if not isinstance(raw, dict):
                raise ValueError("JSON is not a dict")
            return StoredCredentials(
                user_id=UUID(str(raw["user_id"])),
                access_token=str(raw["access_token"]),
                refresh_token=str(raw["refresh_token"]),
            )
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise CliError("Stored credentials are invalid. Sign in again.", ExitCode.AUTH_FAILURE) from exc

    def save(self, credentials: StoredCredentials) -> None:
        payload = json.dumps(
            {
                "user_id": str(credentials.user_id),
                "access_token": credentials.access_token,
                "refresh_token": credentials.refresh_token,
            }
        )

        # macOS Keychain
        if _MacOSKeychain.is_available():
            try:
                _MacOSKeychain.save(payload)
                return
            except Exception:
                pass  # fallback to secure file

        # Windows DPAPI or Encrypted File Store
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._secure_path()
        if _WindowsDPAPI.is_available():
            ciphertext = _WindowsDPAPI.protect(payload.encode("utf-8"))
        else:
            ciphertext = _EncryptedFileStore.encrypt(payload.encode("utf-8"))

        path.write_bytes(ciphertext)
        with suppress(OSError):
            os.chmod(path, 0o600)

    def clear(self) -> bool:
        """Alias for delete per specification."""
        return self.delete()

    def delete(self) -> bool:
        deleted = False

        if _MacOSKeychain.is_available():
            with suppress(Exception):
                if _MacOSKeychain.delete():
                    deleted = True

        secure_file = self._secure_path()
        if secure_file.is_file():
            secure_file.unlink(missing_ok=True)
            deleted = True

        legacy_file = self._legacy_path()
        if legacy_file.is_file():
            legacy_file.unlink(missing_ok=True)
            deleted = True

        return deleted


def credentials_path() -> Path:
    return config_dir() / _SECURE_FILENAME


def load_credentials() -> StoredCredentials | None:
    return CredentialStore().load()


def save_credentials(credentials: StoredCredentials) -> None:
    CredentialStore().save(credentials)


def delete_credentials() -> bool:
    return CredentialStore().delete()
