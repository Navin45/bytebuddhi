"""Normalized external identity returned by OAuth adapters."""

from dataclasses import dataclass

from app.domain.value_objects.identity_provider import IdentityProvider


@dataclass(frozen=True)
class ExternalIdentityData:
    """Provider-agnostic identity. Provider payloads must not escape adapters."""

    provider: IdentityProvider
    subject: str
    email: str | None
    email_verified: bool
    display_name: str | None
    avatar_url: str | None
