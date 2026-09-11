"""Unit tests for URL safety policy, IP classification, and canonicalization."""

import ipaddress

import pytest

from app.application.web.url_policy import (
    UrlSafetyPolicy,
    canonicalize_url,
    is_blocked_ip,
    try_parse_ip_literal,
)
from app.domain.exceptions.web_exceptions import PrivateAddressBlocked, UnsafeUrl
from tests.fixtures.web.fakes import StaticResolver


def _policy(mapping: dict[str, tuple[str, ...]] | None = None) -> UrlSafetyPolicy:
    return UrlSafetyPolicy(resolver=StaticResolver(mapping or {}))


@pytest.mark.asyncio
async def test_http_and_https_allowed_for_public_ip() -> None:
    policy = _policy({"example.com": ("8.8.8.8",)})
    https_url = await policy.assert_safe("https://example.com/path")
    http_url = await policy.assert_safe("http://example.com/path")
    assert https_url.startswith("https://")
    assert http_url.startswith("http://")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "data:text/html,hi",
        "javascript:alert(1)",
        "blob:https://example.com/1",
        "chrome://settings",
        "about:blank",
        "resource://gre/modules/x.jsm",
    ],
)
@pytest.mark.asyncio
async def test_unsupported_schemes_blocked(url: str) -> None:
    policy = _policy()
    with pytest.raises(UnsafeUrl):
        await policy.assert_safe(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost",
        "http://localhost/admin",
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/secret",
        "http://[::1]/",
        "http://0.0.0.0/",
    ],
)
@pytest.mark.asyncio
async def test_loopback_and_localhost_blocked(url: str) -> None:
    policy = _policy({"localhost": ("127.0.0.1",)})
    with pytest.raises((PrivateAddressBlocked, UnsafeUrl)):
        await policy.assert_safe(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5/",
        "http://172.16.4.1/",
        "http://192.168.1.20/",
    ],
)
@pytest.mark.asyncio
async def test_rfc1918_blocked(url: str) -> None:
    policy = _policy()
    with pytest.raises(PrivateAddressBlocked):
        await policy.assert_safe(url)


@pytest.mark.asyncio
async def test_cloud_metadata_ipv4_blocked() -> None:
    policy = _policy()
    with pytest.raises(PrivateAddressBlocked):
        await policy.assert_safe("http://169.254.169.254/latest/meta-data/")


@pytest.mark.asyncio
async def test_metadata_hostname_blocked() -> None:
    policy = _policy({"metadata.google.internal": ("169.254.169.254",)})
    with pytest.raises(PrivateAddressBlocked):
        await policy.assert_safe("http://metadata.google.internal/")


@pytest.mark.asyncio
async def test_dns_to_private_ip_blocked() -> None:
    policy = _policy({"evil.example": ("10.1.2.3",)})
    with pytest.raises(PrivateAddressBlocked):
        await policy.assert_safe("https://evil.example/ssrf")


@pytest.mark.asyncio
async def test_decimal_ipv4_loopback_blocked() -> None:
    policy = _policy()
    with pytest.raises(PrivateAddressBlocked):
        await policy.assert_safe("http://2130706433/")  # 127.0.0.1


@pytest.mark.asyncio
async def test_embedded_credentials_blocked() -> None:
    policy = _policy({"example.com": ("8.8.8.8",)})
    with pytest.raises(UnsafeUrl):
        await policy.assert_safe("https://user:pass@example.com/")


@pytest.mark.asyncio
async def test_redirect_to_private_ip_blocked() -> None:
    policy = _policy({"public.example": ("8.8.8.8",)})
    with pytest.raises(PrivateAddressBlocked):
        await policy.resolve_redirect("https://public.example/page", "http://127.0.0.1/secret")


@pytest.mark.asyncio
async def test_relative_redirect_stays_on_validated_host() -> None:
    policy = _policy({"public.example": ("8.8.8.8",)})
    target = await policy.resolve_redirect("https://public.example/page", "/next")
    assert "public.example" in target


def test_is_blocked_ip_covers_cgnat_and_unspecified() -> None:
    assert is_blocked_ip(ipaddress.ip_address("100.64.1.1"))
    assert is_blocked_ip(ipaddress.ip_address("0.0.0.1"))
    assert is_blocked_ip(ipaddress.ip_address("::1"))
    assert is_blocked_ip(ipaddress.ip_address("fc00::1"))
    assert not is_blocked_ip(ipaddress.ip_address("8.8.8.8"))


def test_try_parse_ip_literal_decimal() -> None:
    parsed = try_parse_ip_literal("2130706433")
    assert parsed == ipaddress.IPv4Address("127.0.0.1")


def test_canonicalize_url_drops_fragment_and_default_port() -> None:
    assert canonicalize_url("HTTPS://Example.COM:443/a/b#frag") == "https://example.com/a/b"
    assert canonicalize_url("http://example.com:80/x?q=1") == "http://example.com/x?q=1"
    left = canonicalize_url("https://example.com/a")
    right = canonicalize_url("https://example.com/a/")
    assert left != right
