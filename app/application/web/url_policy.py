"""URL safety policy for untrusted web research URLs.

Validates scheme, hostname, DNS-resolved addresses, and redirect targets
before any network connection is made.

DNS-rebinding limitation: this policy resolves and inspects addresses before
the HTTP client connects. The subsequent HTTP library may resolve the hostname
again. That race is documented and is not claimed to be a perfect guarantee.
Redirect targets are always re-validated. IP-literal URLs are classified
without DNS.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import ParseResult, urljoin, urlparse, urlunparse

from app.domain.exceptions.web_exceptions import PrivateAddressBlocked, UnsafeUrl

_ALLOWED_SCHEMES = frozenset({"http", "https"})

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "metadata.google.com",
        "kubernetes",
        "kubernetes.default",
        "kubernetes.default.svc",
        "kubernetes.default.svc.cluster.local",
        "instance-data",
    }
)

_BLOCKED_HOSTNAME_SUFFIXES = (".localhost", ".internal", ".localdomain")

# Extra networks not fully covered by ipaddress flags (CGNAT, IPv4 "this" net).
_EXTRA_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("192.0.0.0/29"),  # IPv4 special-purpose including 192.0.0.8
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("255.255.255.255/32"),
)

_METADATA_IPV6 = (
    ipaddress.ip_address("fd00:ec2::254"),
    ipaddress.ip_address("fe80::a9fe:a9fe"),
)


class HostnameResolver:
    """Async DNS resolver used by UrlSafetyPolicy."""

    async def resolve(self, hostname: str) -> tuple[str, ...]:
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(
                hostname,
                None,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise UnsafeUrl(f"DNS resolution failed for host '{hostname}'", url=hostname) from exc
        addresses = tuple(sorted({str(info[4][0]) for info in infos if info[4]}))
        if not addresses:
            raise UnsafeUrl(f"DNS resolution returned no addresses for host '{hostname}'", url=hostname)
        return addresses


@dataclass(frozen=True)
class UrlSafetyPolicy:
    """Validates untrusted URLs before fetch or browser navigation.

    `allowlisted_hosts` and `allowlisted_networks` exist only so deterministic
    local test servers can be used. Production configuration must leave them empty.
    """

    resolver: HostnameResolver
    allowed_schemes: frozenset[str] = _ALLOWED_SCHEMES
    allowlisted_hosts: frozenset[str] = frozenset()
    allowlisted_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()

    async def assert_safe(self, url: str) -> str:
        """Parse, validate, resolve, and return a normalized URL string.

        Raises:
            UnsafeUrl: unsupported scheme, missing host, credentials, or bad hostname.
            PrivateAddressBlocked: resolved or literal address is internal/reserved.
        """
        parsed = _parse_http_url(url)
        host = parsed.hostname
        if host is None:
            raise UnsafeUrl("URL is missing a hostname", url=url)
        host_lower = host.lower().rstrip(".")
        if _has_userinfo(parsed):
            raise UnsafeUrl("URLs with embedded credentials are not allowed", url=url)
        if not _is_allowlisted_host(host_lower, self.allowlisted_hosts):
            _assert_hostname_not_blocked(host_lower, url)

        ip_literal = try_parse_ip_literal(host_lower)
        if ip_literal is not None:
            if not _is_allowlisted_ip(ip_literal, self.allowlisted_hosts, self.allowlisted_networks):
                _assert_public_ip(ip_literal, url)
            return _normalized_url(parsed)

        addresses = await self.resolver.resolve(host_lower)
        for address in addresses:
            parsed_ip = ipaddress.ip_address(address)
            if _is_allowlisted_ip(parsed_ip, self.allowlisted_hosts, self.allowlisted_networks):
                continue
            _assert_public_ip(parsed_ip, url)
        return _normalized_url(parsed)

    async def resolve_redirect(self, current_url: str, location: str | None) -> str:
        """Resolve a redirect Location against the current URL and validate it."""
        if not location or not location.strip():
            raise UnsafeUrl("Redirect response is missing a Location header", url=current_url)
        target = urljoin(current_url, location.strip())
        return await self.assert_safe(target)


def try_parse_ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse a hostname that is actually a literal IP, including decimal IPv4."""
    candidate = host.strip().strip("[]")
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        pass
    if candidate.isdigit():
        value = int(candidate)
        if 0 <= value <= 0xFFFFFFFF:
            return ipaddress.IPv4Address(value)
    return None


def canonicalize_url(url: str) -> str:
    """Normalize a URL for deduplication without merging distinct resources.

    Lowercases scheme and host, drops default ports and fragments, keeps path and query.
    """
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower().rstrip(".")
    if not scheme or not host:
        return url.strip()
    port = parsed.port
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    else:
        netloc = host
    path = parsed.path or "/"
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if the address is loopback, private, link-local, reserved, or metadata."""
    if ip.version == 6:
        ipv6 = ipaddress.IPv6Address(ip)
        if ipv6.ipv4_mapped is not None:
            return is_blocked_ip(ipv6.ipv4_mapped)
        if ipv6.sixtofour is not None:
            return is_blocked_ip(ipv6.sixtofour)
        if ipv6.teredo is not None:
            return True
        if ipv6 in _METADATA_IPV6:
            return True
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or getattr(ip, "is_site_local", False)
    ):
        return True
    return any(ip in network for network in _EXTRA_BLOCKED_NETWORKS)


def _parse_http_url(url: str) -> ParseResult:
    if not url or not str(url).strip():
        raise UnsafeUrl("URL must not be empty", url=url)
    raw = str(url).strip()
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrl(
            f"URL scheme '{scheme or '(none)'}' is not allowed; only http and https are permitted",
            url=raw,
        )
    if parsed.hostname is None:
        raise UnsafeUrl("URL is missing a hostname", url=raw)
    return parsed


def _normalized_url(parsed: ParseResult) -> str:
    return urlunparse(parsed)


def _has_userinfo(parsed: ParseResult) -> bool:
    username = getattr(parsed, "username", None)
    password = getattr(parsed, "password", None)
    return bool(username or password)


def _assert_hostname_not_blocked(host: str, url: str) -> None:
    if host in _BLOCKED_HOSTNAMES:
        raise PrivateAddressBlocked(f"Host '{host}' is not allowed", url=url)
    for suffix in _BLOCKED_HOSTNAME_SUFFIXES:
        if host.endswith(suffix):
            raise PrivateAddressBlocked(f"Host '{host}' is not allowed", url=url)
    if host.endswith(".internal"):
        raise PrivateAddressBlocked(f"Host '{host}' is not allowed", url=url)


def _is_allowlisted_host(host: str, allowlisted_hosts: frozenset[str]) -> bool:
    return host.lower() in {item.lower() for item in allowlisted_hosts}


def _is_allowlisted_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    allowlisted_hosts: frozenset[str],
    allowlisted_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> bool:
    if str(ip) in allowlisted_hosts:
        return True
    return any(ip in network for network in allowlisted_networks)


def _assert_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, url: str) -> None:
    if is_blocked_ip(ip):
        raise PrivateAddressBlocked(
            f"Address {ip} is private, loopback, link-local, or otherwise reserved",
            url=url,
        )
