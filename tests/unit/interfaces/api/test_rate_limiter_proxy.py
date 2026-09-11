"""Trusted-proxy handling for process-local rate limiting."""

from unittest.mock import MagicMock

from app.interfaces.api.middleware.rate_limiter import RateLimitMiddleware


def _request(peer: str, forwarded: str | None = None) -> MagicMock:
    request = MagicMock()
    request.client.host = peer
    request.headers.get.side_effect = lambda key, default=None: forwarded if key == "X-Forwarded-For" else default
    return request


def test_untrusted_peer_cannot_spoof_forwarded_for() -> None:
    limiter = RateLimitMiddleware(app=MagicMock())
    limiter._trusted_proxies = {"10.0.0.1"}
    ip = limiter._get_client_ip(_request("8.8.8.8", forwarded="1.2.3.4"))
    assert ip == "8.8.8.8"


def test_trusted_proxy_uses_forwarded_for() -> None:
    limiter = RateLimitMiddleware(app=MagicMock())
    limiter._trusted_proxies = {"10.0.0.1"}
    ip = limiter._get_client_ip(_request("10.0.0.1", forwarded="203.0.113.9, 10.0.0.1"))
    assert ip == "203.0.113.9"
