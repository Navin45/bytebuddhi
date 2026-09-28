"""Deterministic redaction test suite for ByteBuddhi diagnostics and support bundle."""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from unittest.mock import patch

from app._version import APP_VERSION, PROTOCOL_VERSION
from app.interfaces.cli.doctor import (
    export_support_bundle,
    sanitize_env,
    sanitize_text,
)

SECRET_FIXTURES = {
    "bearer": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLWFkZGljdCJ9.signature12345",
    "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0.signature67890",
    "openai_key": "sk-1234567890abcdef1234567890abcdef12345678",
    "github_token": "ghp_1234567890abcdef1234567890abcdef123456",
    "google_key": "AIzaSyD1234567890abcdef1234567890abcdef",
    "password": "SuperSecretPassword999!",
    "prompt": "Fix the secret security vulnerability in repo private-core",
}


def test_sanitize_text_deterministic_redaction():
    text = (
        f"Request with {SECRET_FIXTURES['bearer']} and jwt={SECRET_FIXTURES['jwt']}\n"
        f"OpenAI: {SECRET_FIXTURES['openai_key']}\n"
        f"GitHub: {SECRET_FIXTURES['github_token']}\n"
        f"Google: {SECRET_FIXTURES['google_key']}\n"
        f"password: {SECRET_FIXTURES['password']}\n"
        f"prompt: '{SECRET_FIXTURES['prompt']}'\n"
    )

    scrubbed = sanitize_text(text)

    for name, secret in SECRET_FIXTURES.items():
        assert secret not in scrubbed, f"Secret '{name}' ({secret}) leaked through sanitize_text!"


def test_sanitize_env_deterministic_redaction():
    env = {
        "PATH": "/usr/bin:/bin",
        "BYTEBUDDHI_TOKEN": SECRET_FIXTURES["jwt"],
        "DATABASE_PASSWORD": SECRET_FIXTURES["password"],
        "OPENAI_API_KEY": SECRET_FIXTURES["openai_key"],
        "GITHUB_TOKEN": SECRET_FIXTURES["github_token"],
        "SYSTEM_USER": "testuser",
        "INLINE_SECRET": f"prefix-{SECRET_FIXTURES['openai_key']}-suffix",
    }

    scrubbed = sanitize_env(env)

    # Sensitive keys must be fully masked
    assert scrubbed["BYTEBUDDHI_TOKEN"] == "[REDACTED]"
    assert scrubbed["DATABASE_PASSWORD"] == "[REDACTED]"
    assert scrubbed["OPENAI_API_KEY"] == "[REDACTED]"
    assert scrubbed["GITHUB_TOKEN"] == "[REDACTED]"

    # Non-sensitive keys are preserved
    assert scrubbed["PATH"] == "/usr/bin:/bin"
    assert scrubbed["SYSTEM_USER"] == "testuser"

    # Inline secrets in other values are scrubbed
    assert SECRET_FIXTURES["openai_key"] not in scrubbed["INLINE_SECRET"]


def test_support_bundle_deterministic_redaction(tmp_path: Path):
    """Create fixture files containing tokens, passwords, keys, and prompts.

    Export support bundle and assert zero secrets appear in ANY file within the zip archive.
    """
    mock_config_dir = tmp_path / "config"
    mock_config_dir.mkdir(parents=True)

    # 1. Config file with sensitive keys
    config_file = mock_config_dir / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "config_version": 1,
                "channel": "stable",
                "auth_token": SECRET_FIXTURES["bearer"],
                "api_key": SECRET_FIXTURES["openai_key"],
                "db_password": SECRET_FIXTURES["password"],
                "theme": "system",
            }
        ),
        encoding="utf-8",
    )

    # 2. Gateway log containing bearer tokens, passwords, and user prompts
    log_file = mock_config_dir / "gateway.log"
    log_file.write_text(
        f"2026-09-28 10:00:00 INFO Authorized user with {SECRET_FIXTURES['bearer']}\n"
        f"2026-09-28 10:00:01 DEBUG Handshake token {SECRET_FIXTURES['jwt']}\n"
        f"2026-09-28 10:00:02 INFO Connecting to provider with key={SECRET_FIXTURES['openai_key']}\n"
        f"2026-09-28 10:00:03 INFO DB connect with password='{SECRET_FIXTURES['password']}'\n"
        f"2026-09-28 10:00:04 INFO User submitted prompt='{SECRET_FIXTURES['prompt']}'\n",
        encoding="utf-8",
    )

    # 3. Environment with secrets
    test_env = {
        "PATH": "/usr/local/bin:/usr/bin",
        "BYTEBUDDHI_AUTH": SECRET_FIXTURES["bearer"],
        "SECRET_KEY": SECRET_FIXTURES["password"],
        "OPENAI_API_KEY": SECRET_FIXTURES["openai_key"],
        "GITHUB_TOKEN": SECRET_FIXTURES["github_token"],
    }

    diag = {
        "version": {
            "application": APP_VERSION,
            "protocol": PROTOCOL_VERSION,
            "min_protocol": 1,
        },
        "platform": {
            "os": "win32",
            "machine": "x86_64",
            "python_version": "3.13.0",
        },
        "runtime_installation": {
            "is_managed": True,
        },
        "configuration": {
            "update_channel": "stable",
        },
        "authentication": {
            "authenticated": True,
            "backend": "Windows DPAPI",
        },
        "gateway": {
            "live": True,
            "ready": True,
            "service": "ByteBuddhi Gateway",
        },
    }

    zip_dest = tmp_path / "diagnostics.zip"

    with (
        patch("app.interfaces.cli.doctor.config_dir", return_value=mock_config_dir),
        patch.dict(os.environ, test_env, clear=True),
    ):
        bundle_path = export_support_bundle(diag, zip_dest)

    assert bundle_path.is_file()

    # Unpack and verify every single file in the zip
    with zipfile.ZipFile(bundle_path, "r") as zf:
        archive_files = zf.namelist()
        assert "diagnostics.json" in archive_files
        assert "config_metadata.json" in archive_files
        assert "gateway_sanitized.log" in archive_files
        assert "system_env.json" in archive_files

        for file_name in archive_files:
            content = zf.read(file_name).decode("utf-8", errors="replace")

            # Assert ZERO fixture secrets leaked into ANY file in the bundle
            for secret_name, secret_val in SECRET_FIXTURES.items():
                assert secret_val not in content, (
                    f"LEAK DETECTED: {secret_name} was found in {file_name} of support bundle!\n"
                    f"Content snippet: {content[:300]}"
                )

        # Assert expected operational fields ARE present
        diag_json = json.loads(zf.read("diagnostics.json").decode("utf-8"))
        assert diag_json["version"]["application"] == APP_VERSION
        assert diag_json["version"]["protocol"] == PROTOCOL_VERSION
        assert diag_json["platform"]["os"] == "win32"
        assert diag_json["gateway"]["live"] is True
