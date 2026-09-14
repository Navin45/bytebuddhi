"""PKCE and OAuth state token generation. Stdlib only."""

from __future__ import annotations

import base64
import hashlib
import secrets


def random_state() -> str:
    """Cryptographically random, URL-safe OAuth state."""
    return secrets.token_urlsafe(32)


def random_exchange_code() -> str:
    """Short-lived one-time ByteBuddhi token-exchange code."""
    return secrets.token_urlsafe(32)


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, S256 code_challenge)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge
