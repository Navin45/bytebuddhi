"""GatewayClient HTTP behavior. Task submission is not retried."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
import websockets

from app.interfaces.cli.credentials import CredentialStore, StoredCredentials
from app.interfaces.gateway.client import (
    AGENT_READ_TIMEOUT_SECONDS,
    API_READ_TIMEOUT_SECONDS,
    CONNECT_TIMEOUT_SECONDS,
    STREAM_READ_TIMEOUT_SECONDS,
    GatewayClient,
    agent_timeout,
    api_timeout,
    stream_timeout,
)
from app.interfaces.gateway.errors import (
    AuthenticationRequired,
    AuthorizationDenied,
    Conflict,
    GatewayServerError,
    GatewayUnavailable,
    InvalidRequest,
    MalformedResponse,
    RateLimited,
    ResourceNotFound,
)


def _client(handler, **kwargs) -> GatewayClient:
    async def _sleep(_seconds: float) -> None:
        return None

    return GatewayClient(
        "http://127.0.0.1:8765",
        token="super-secret-access-token",
        transport=httpx.MockTransport(handler),
        sleep=_sleep,
        **kwargs,
    )


def test_timeouts_are_finite_and_distinct() -> None:
    connect = api_timeout()
    agent = agent_timeout()
    stream = stream_timeout()
    for timeout in (connect, agent, stream):
        assert timeout.connect == CONNECT_TIMEOUT_SECONDS
        assert timeout.read is not None
        assert timeout.write is not None
        assert timeout.pool is not None
    assert connect.read == API_READ_TIMEOUT_SECONDS
    assert agent.read == AGENT_READ_TIMEOUT_SECONDS
    assert stream.read == STREAM_READ_TIMEOUT_SECONDS
    assert agent.read > connect.read


@pytest.mark.asyncio
async def test_authorization_header_and_no_token_in_repr() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "ok", "service": "ByteBuddhi API", "version": "0.1.3"})

    client = _client(handler)
    assert "super-secret-access-token" not in repr(client)
    try:
        health = await client.health()
    finally:
        await client.aclose()
    assert health.status == "ok"
    assert seen[0].headers["authorization"] == "Bearer super-secret-access-token"
    assert client._http.follow_redirects is False
    assert client._http.trust_env is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, AuthenticationRequired),
        (403, AuthorizationDenied),
        (404, ResourceNotFound),
        (409, Conflict),
        (422, InvalidRequest),
        (429, RateLimited),
        (500, GatewayServerError),
        (503, GatewayServerError),
    ],
)
async def test_status_mapping(status_code: int, error_type: type[Exception]) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"detail": "Bearer super-secret-access-token expired"})

    client = _client(handler)
    try:
        with pytest.raises(error_type) as exc:
            await client.list_projects()
    finally:
        await client.aclose()
    assert "super-secret-access-token" not in str(exc.value)


@pytest.mark.asyncio
async def test_malformed_response_does_not_leak_token() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"detail": "super-secret-access-token"})

    client = _client(handler, debug=True)
    try:
        with pytest.raises(MalformedResponse) as exc:
            await client.create_run(prompt="hello")
    finally:
        await client.aclose()
    assert "super-secret-access-token" not in str(exc.value)


@pytest.mark.asyncio
async def test_failure_log_does_not_leak_token(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, dict]] = []

    class _Logger:
        def warning(self, event: str, **kwargs: object) -> None:
            events.append((str(event), dict(kwargs)))

        def info(self, *_args: object, **_kwargs: object) -> None:
            return None

    monkeypatch.setattr("app.interfaces.gateway.client.logger", _Logger())

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "super-secret-access-token"})

    client = _client(handler)
    try:
        with pytest.raises(GatewayServerError) as exc:
            await client.create_run(prompt="hello")
    finally:
        await client.aclose()
    rendered = str(exc.value) + str(events)
    assert "super-secret-access-token" not in rendered
    assert events[0][0] == "gateway_client_request_failed"
    assert "authorization" not in events[0][1]


@pytest.mark.asyncio
async def test_task_submission_is_not_retried() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ConnectError("refused")

    client = _client(handler)
    try:
        with pytest.raises(GatewayUnavailable) as exc:
            await client.create_run(prompt="do not run twice")
    finally:
        await client.aclose()
    assert calls["count"] == 1
    assert "embedded" in str(exc.value)


@pytest.mark.asyncio
async def test_health_retries_are_bounded() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 3:
            return httpx.Response(503, json={"status": "starting"})
        return httpx.Response(200, json={"status": "ok", "service": "ByteBuddhi API", "version": "0.1.3"})

    client = _client(handler)
    try:
        health = await client.health()
    finally:
        await client.aclose()
    assert health.version == "0.1.3"
    assert calls["count"] == 3


@pytest.mark.asyncio
async def test_create_run_uses_agent_timeout_and_parses_contract() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["idempotency"] = request.headers.get("Idempotency-Key")
        return httpx.Response(
            202,
            json={
                "run_id": "run_1",
                "conversation_id": None,
                "status": "queued",
            },
        )

    client = _client(handler)
    original = client._http.request

    async def _request(*args, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return await original(*args, **kwargs)

    client._http.request = _request  # type: ignore[method-assign]
    try:
        result = await client.create_run(prompt="hello")
    finally:
        await client.aclose()
    assert seen["path"] == "/api/v1/runs"
    assert seen["method"] == "POST"
    timeout = seen["timeout"]
    assert getattr(timeout, "read", None) == API_READ_TIMEOUT_SECONDS
    assert result.status == "queued"
    assert result.run_id == "run_1"
    assert seen["idempotency"]
    assert "super-secret-access-token" not in str(seen["idempotency"])


@pytest.mark.asyncio
async def test_remote_client_refuses_local_paths_without_a_request() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("remote client must not send a filesystem path")

    client = _client(handler, local_gateway=False)
    try:
        with pytest.raises(InvalidRequest):
            await client.resolve_local_project("/tmp/project")
    finally:
        await client.aclose()


def _envelope(run_id: str, sequence: int, event_type: str, data: dict | None = None) -> str:
    return json.dumps(
        {
            "event_id": f"evt_{sequence}",
            "run_id": run_id,
            "sequence": sequence,
            "type": event_type,
            "schema_version": 1,
            "created_at": "2026-09-25T00:00:00+00:00",
            "data": data or {},
        }
    )


class _Socket:
    def __init__(self, messages: list[str]) -> None:
        self._messages = list(messages)

    async def recv(self) -> str:
        if not self._messages:
            raise websockets.exceptions.ConnectionClosed(None, None)
        return self._messages.pop(0)

    async def __aenter__(self) -> _Socket:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_stream_replays_in_order_and_reconnects_without_creating_a_run(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = "run_stream"
    connects: list[dict[str, object]] = []
    scripts = [
        [_envelope(run_id, 1, "run_started")],
        [_envelope(run_id, 2, "assistant_delta", {"delta": "Hi"}), _envelope(run_id, 3, "run_completed")],
    ]

    def connect(url: str, **kwargs: object) -> _Socket:
        connects.append(
            {"url": url, "headers": kwargs.get("additional_headers"), "proxy": kwargs.get("proxy", "missing")}
        )
        return _Socket(scripts.pop(0))

    monkeypatch.setattr(websockets, "connect", connect)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("stream reconnect must not create a run")

    client = _client(handler)
    try:
        events = [item async for item in client.stream_run(run_id)]
    finally:
        await client.aclose()
    assert [item["sequence"] for item in events] == [1, 2, 3]
    assert events[-1]["type"] == "run_completed"
    url = connects[1]["url"]
    assert isinstance(url, str)
    assert url.endswith("after_sequence=1")
    assert connects[0]["proxy"] is None
    assert connects[0]["headers"] == {"Authorization": "Bearer super-secret-access-token"}


@pytest.mark.asyncio
async def test_stream_fills_a_sequence_gap_from_the_event_api(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = "run_gap"

    def connect(_url: str, **_kwargs: object) -> _Socket:
        return _Socket(
            [
                _envelope(run_id, 1, "run_started"),
                _envelope(run_id, 3, "run_completed", {"conversation_id": str(uuid4())}),
            ]
        )

    monkeypatch.setattr(websockets, "connect", connect)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "after_sequence=1" in str(request.url)
        return httpx.Response(
            200,
            json={
                "events": [
                    json.loads(_envelope(run_id, 2, "assistant_delta", {"delta": "gap"})),
                    json.loads(_envelope(run_id, 3, "run_completed")),
                ],
                "next_sequence": 3,
                "has_more": False,
            },
        )

    client = _client(handler)
    try:
        events = [item async for item in client.stream_run(run_id)]
    finally:
        await client.aclose()
    assert [item["sequence"] for item in events] == [1, 2, 3]
    assert events[1]["data"]["delta"] == "gap"


@pytest.mark.asyncio
async def test_stream_stops_after_bounded_reconnects(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"count": 0}

    def connect(_url: str, **_kwargs: object) -> _Socket:
        attempts["count"] += 1
        return _Socket([])

    monkeypatch.setattr(websockets, "connect", connect)
    client = _client(lambda _request: httpx.Response(500))
    try:
        with pytest.raises(GatewayUnavailable):
            async for _event in client.stream_run("run_down"):
                pass
    finally:
        await client.aclose()
    assert attempts["count"] == 4


def test_credential_repr_hides_tokens(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYTEBUDDHI_CONFIG_DIR", str(tmp_path))
    stored = StoredCredentials(
        user_id=uuid4(), access_token="super-secret-access-token", refresh_token="refresh-secret-value"
    )
    CredentialStore().save(stored)
    loaded = CredentialStore().load()
    assert loaded is not None
    assert "super-secret-access-token" not in repr(loaded)
    assert "refresh-secret-value" not in repr(loaded)


@pytest.mark.asyncio
async def test_lists_conversations_and_messages() -> None:
    conversation_id = uuid4()
    user_id = uuid4()
    message_id = uuid4()
    now = "2026-09-25T00:00:00+00:00"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/conversations"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": str(conversation_id),
                        "user_id": str(user_id),
                        "project_id": None,
                        "title": "Audit",
                        "is_archived": False,
                        "metadata": None,
                        "message_count": 1,
                        "created_at": now,
                        "updated_at": now,
                    }
                ],
            )
        return httpx.Response(
            200,
            json=[
                {
                    "id": str(message_id),
                    "conversation_id": str(conversation_id),
                    "role": "assistant",
                    "content": "Hello",
                    "created_at": now,
                    "metadata": None,
                    "parent_message_id": None,
                    "feedback": None,
                }
            ],
        )

    client = _client(handler)
    try:
        conversations = await client.list_conversations()
        messages = await client.list_messages(conversation_id)
    finally:
        await client.aclose()
    assert conversations[0].title == "Audit"
    assert messages[0].content == "Hello"
    assert "super-secret-access-token" not in messages[0].content
