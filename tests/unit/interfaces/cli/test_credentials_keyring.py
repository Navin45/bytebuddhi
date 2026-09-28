"""Unit tests for OS-backed secure credential storage and migration."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from app.interfaces.cli.credentials import CredentialStore, StoredCredentials


def test_credential_store_save_and_load(tmp_path: Path):
    store = CredentialStore(tmp_path)
    creds = StoredCredentials(user_id=uuid4(), access_token="token_abc", refresh_token="token_xyz")

    store.save(creds)
    loaded = store.load()

    assert loaded is not None
    assert loaded.user_id == creds.user_id
    assert loaded.access_token == "token_abc"
    assert loaded.refresh_token == "token_xyz"


def test_credential_store_clear(tmp_path: Path):
    store = CredentialStore(tmp_path)
    creds = StoredCredentials(user_id=uuid4(), access_token="token_abc", refresh_token="token_xyz")

    store.save(creds)
    assert store.load() is not None

    assert store.clear() is True
    assert store.load() is None


def test_credential_store_migrates_legacy_plaintext(tmp_path: Path):
    store = CredentialStore(tmp_path)
    uid = uuid4()

    legacy_file = tmp_path / "credentials.json"
    legacy_file.write_text(
        json.dumps(
            {
                "user_id": str(uid),
                "access_token": "legacy_access",
                "refresh_token": "legacy_refresh",
            }
        ),
        encoding="utf-8",
    )
    assert legacy_file.is_file()

    # Load should detect legacy file and migrate
    loaded = store.load()
    assert loaded is not None
    assert loaded.user_id == uid
    assert loaded.access_token == "legacy_access"
    assert loaded.refresh_token == "legacy_refresh"

    # Legacy file must have been securely deleted after migration
    assert not legacy_file.exists()

    # Next load should load from secure store
    second_load = store.load()
    assert second_load is not None
    assert second_load.user_id == uid


def test_credential_repr_never_leaks_tokens():
    creds = StoredCredentials(user_id=uuid4(), access_token="SUPER_SECRET_JWT", refresh_token="SUPER_SECRET_REFRESH")
    rep = repr(creds)
    assert "SUPER_SECRET" not in rep
    assert str(creds.user_id) in rep
