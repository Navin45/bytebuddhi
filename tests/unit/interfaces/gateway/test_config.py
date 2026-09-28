"""Gateway URL, bind address, and execution-mode resolution."""

from app.interfaces.gateway.config import (
    resolve_bind_address,
    resolve_execution_mode,
    resolve_gateway_endpoint,
)
from app.interfaces.gateway.errors import GatewayConfigError


def test_default_local_gateway_url() -> None:
    endpoint = resolve_gateway_endpoint(None, environ={})
    assert endpoint.url == "http://127.0.0.1:8765"
    assert endpoint.source == "default"
    assert endpoint.local is True


def test_explicit_url_beats_environment() -> None:
    env = {
        "BYTEBUDDHI_GATEWAY_URL": "http://127.0.0.1:9000",
        "BYTEBUDDHI_API_URL": "http://127.0.0.1:8000",
    }
    endpoint = resolve_gateway_endpoint("https://gateway.example", environ=env)
    assert endpoint.url == "https://gateway.example:443"
    assert endpoint.source == "explicit"
    assert endpoint.local is False


def test_gateway_url_beats_api_url() -> None:
    env = {
        "BYTEBUDDHI_GATEWAY_URL": "http://10.0.0.5:9000",
        "BYTEBUDDHI_API_URL": "http://127.0.0.1:8000",
    }
    endpoint = resolve_gateway_endpoint(None, environ=env)
    assert endpoint.url == "http://10.0.0.5:9000"
    assert endpoint.source == "BYTEBUDDHI_GATEWAY_URL"
    assert endpoint.local is False


def test_api_url_used_when_gateway_url_absent() -> None:
    endpoint = resolve_gateway_endpoint(None, environ={"BYTEBUDDHI_API_URL": "http://127.0.0.1:8000"})
    assert endpoint.url == "http://127.0.0.1:8000"
    assert endpoint.source == "BYTEBUDDHI_API_URL"
    assert endpoint.local is False


def test_custom_port_changes_local_default() -> None:
    env = {"BYTEBUDDHI_GATEWAY_PORT": "9100"}
    endpoint = resolve_gateway_endpoint(None, environ=env)
    assert endpoint.url == "http://127.0.0.1:9100"
    assert endpoint.local is True


def test_malformed_urls_are_rejected() -> None:
    for raw in (
        "not a url",
        "ftp://127.0.0.1:8765",
        "http://user:secret@127.0.0.1:8765",
        "http://127.0.0.1:8765/api/v1",
    ):
        try:
            resolve_gateway_endpoint(raw, environ={})
        except GatewayConfigError as exc:
            assert exc.usage is True
            assert "secret" not in exc.message
        else:
            raise AssertionError(raw)


def test_wildcard_bind_requires_explicit_host() -> None:
    implicit = resolve_bind_address(None, None, environ={})
    assert implicit.host == "127.0.0.1"
    assert implicit.exposed is False
    explicit = resolve_bind_address("0.0.0.0", 8765, environ={})
    assert explicit.host == "0.0.0.0"
    assert explicit.exposed is True
    assert explicit.url == "http://127.0.0.1:8765"


def test_execution_mode_defaults_to_gateway_and_embedded_is_explicit() -> None:
    assert resolve_execution_mode(embedded_flag=False, environ={}) == "gateway"
    assert resolve_execution_mode(embedded_flag=True, environ={"BYTEBUDDHI_EXECUTION_MODE": "gateway"}) == "embedded"
    assert (
        resolve_execution_mode(
            embedded_flag=False, gateway_flag=True, environ={"BYTEBUDDHI_EXECUTION_MODE": "embedded"}
        )
        == "gateway"
    )
    assert resolve_execution_mode(embedded_flag=False, environ={"BYTEBUDDHI_EXECUTION_MODE": "embedded"}) == "embedded"


def test_invalid_execution_mode_and_port() -> None:
    try:
        resolve_execution_mode(embedded_flag=False, environ={"BYTEBUDDHI_EXECUTION_MODE": "local"})
    except GatewayConfigError as exc:
        assert exc.usage is False
    else:
        raise AssertionError("expected config error")
    try:
        resolve_bind_address(None, "nope", environ={})
    except GatewayConfigError:
        return
    raise AssertionError("expected port error")
