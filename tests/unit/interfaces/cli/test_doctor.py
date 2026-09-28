import io
import json
import zipfile
from pathlib import Path

import pytest

from app._version import APP_VERSION
from app.interfaces.cli.doctor import (
    export_support_bundle,
    handle_doctor,
    run_diagnostics,
    sanitize_env,
    sanitize_text,
)


def test_sanitize_text_removes_tokens_and_keys() -> None:
    text = (
        "User auth: Bearer some_secret_token_12345 "
        "and raw_jwt: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0In0.abc12345 "
        "and api_key sk-1234567890123456789012345 and github ghp_123456789012345678901234567890"
    )
    sanitized = sanitize_text(text)
    assert "Bearer [REDACTED]" in sanitized
    assert "[REDACTED_JWT]" in sanitized
    assert "[REDACTED_KEY]" in sanitized
    assert "sk-12345" not in sanitized
    assert "ghp_12345" not in sanitized


def test_sanitize_env_masks_sensitive_names() -> None:
    raw_env = {
        "PATH": "/usr/bin:/bin",
        "BYTEBUDDHI_TOKEN": "secret-token-value",
        "OPENAI_API_KEY": "sk-1234567890123456789012345",
        "USER": "developer",
    }
    sanitized = sanitize_env(raw_env)
    assert sanitized["PATH"] == "/usr/bin:/bin"
    assert sanitized["USER"] == "developer"
    assert sanitized["BYTEBUDDHI_TOKEN"] == "[REDACTED]"
    assert sanitized["OPENAI_API_KEY"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_run_diagnostics_structure() -> None:
    diag = await run_diagnostics("http://127.0.0.1:8765")
    assert "version" in diag
    assert "platform" in diag
    assert "runtime_installation" in diag
    assert "configuration" in diag
    assert "authentication" in diag
    assert "gateway" in diag
    assert "desktop" in diag

    assert diag["version"]["protocol"] == 1
    assert (
        "Windows DPAPI" in diag["authentication"]["backend"]
        or "Secret Service" in diag["authentication"]["backend"]
        or "Keychain" in diag["authentication"]["backend"]
        or "Mock" in diag["authentication"]["backend"]
    )


def test_export_support_bundle_creates_zip(tmp_path: Path) -> None:
    diag = {"version": {"application": "0.1.3", "protocol": 1}, "platform": {"os": "win32"}}
    zip_out = tmp_path / "diagnostics.zip"
    export_support_bundle(diag, zip_out)

    assert zip_out.is_file()
    with zipfile.ZipFile(zip_out, "r") as zf:
        namelist = zf.namelist()
        assert "diagnostics.json" in namelist
        assert "system_env.json" in namelist

        diag_content = json.loads(zf.read("diagnostics.json").decode("utf-8"))
        assert diag_content["version"]["application"] == "0.1.3"


@pytest.mark.asyncio
async def test_handle_doctor_json_mode() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = await handle_doctor(json_mode=True, stdout=stdout, stderr=stderr)
    assert code == 0
    parsed = json.loads(stdout.getvalue())
    assert parsed["version"]["application"] == APP_VERSION
