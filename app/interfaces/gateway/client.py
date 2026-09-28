"""Async HTTP client for the ByteBuddhi gateway. Shared by CLI and future UIs."""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import httpx
import websockets
from pydantic import ValidationError

from app._version import MIN_PROTOCOL_VERSION, PROTOCOL_VERSION
from app.application.runs.sequence import SequenceGap, SequenceTracker
from app.infrastructure.config.logger import get_logger
from app.interfaces.api.schemas.chat_schema import ConversationResponse, MessageResponse
from app.interfaces.api.schemas.model_schema import ModelCatalogResponse
from app.interfaces.api.schemas.project_schema import ProjectResponse
from app.interfaces.api.schemas.run_schema import RunCreateResponse, RunEventPage, RunResponse
from app.interfaces.gateway.errors import (
    AuthenticationRequired,
    AuthorizationDenied,
    Conflict,
    GatewayError,
    GatewayServerError,
    GatewayTimeout,
    GatewayUnavailable,
    InvalidRequest,
    MalformedResponse,
    ProtocolIncompatible,
    RateLimited,
    ResourceNotFound,
    redact_secrets,
)
from app.interfaces.gateway.models import CancelAck, HealthSnapshot, MessageStreamResult, ProbeResult, ReadinessSnapshot

logger = get_logger(__name__)

CONNECT_TIMEOUT_SECONDS = 5.0
API_READ_TIMEOUT_SECONDS = 30.0
AGENT_READ_TIMEOUT_SECONDS = 600.0
STREAM_READ_TIMEOUT_SECONDS = 600.0
WRITE_TIMEOUT_SECONDS = 30.0
SAFE_RETRY_ATTEMPTS = 3
_RUN_ID_RE_RAW = r"^[A-Za-z0-9_-]{1,128}$"
_TERMINAL_RUN_EVENTS = frozenset({"run_completed", "run_failed", "run_cancelled", "run_interrupted"})
_STREAM_RECONNECTS = 3

_STATUS_ERRORS: dict[int, type[GatewayError]] = {
    401: AuthenticationRequired,
    403: AuthorizationDenied,
    404: ResourceNotFound,
    409: Conflict,
    400: InvalidRequest,
    422: InvalidRequest,
    429: RateLimited,
}


def api_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=CONNECT_TIMEOUT_SECONDS,
        read=API_READ_TIMEOUT_SECONDS,
        write=WRITE_TIMEOUT_SECONDS,
        pool=CONNECT_TIMEOUT_SECONDS,
    )


def agent_timeout() -> httpx.Timeout:
    """Finite timeout for a blocking agent run. Retries are not applied to that call."""
    return httpx.Timeout(
        connect=CONNECT_TIMEOUT_SECONDS,
        read=AGENT_READ_TIMEOUT_SECONDS,
        write=WRITE_TIMEOUT_SECONDS,
        pool=CONNECT_TIMEOUT_SECONDS,
    )


def stream_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=CONNECT_TIMEOUT_SECONDS,
        read=STREAM_READ_TIMEOUT_SECONDS,
        write=WRITE_TIMEOUT_SECONDS,
        pool=CONNECT_TIMEOUT_SECONDS,
    )


def probe_timeout() -> httpx.Timeout:
    return httpx.Timeout(connect=2.0, read=2.0, write=2.0, pool=2.0)


class GatewayClient:
    """HTTP transport, authentication header, timeouts, and error mapping.

    The server remains the authority for identity. This client sends
    ``Authorization: Bearer`` and does not verify JWTs or send a user id.
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        local_gateway: bool = False,
        debug: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token or None
        self.local_gateway = local_gateway
        self.debug = debug
        self._sleep = sleep or asyncio.sleep
        self._http = httpx.AsyncClient(
            timeout=api_timeout(),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def __repr__(self) -> str:
        return f"GatewayClient(base_url={self.base_url!r})"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> GatewayClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def health(self) -> HealthSnapshot:
        response = await self._request("GET", "/api/v1/health/live", operation="health", retry=True)
        body = _object(response)
        proto_raw = body.get("protocol_version")
        min_proto_raw = body.get("min_protocol_version")
        protocol_version = int(proto_raw) if proto_raw is not None else None
        min_protocol_version = int(min_proto_raw) if min_proto_raw is not None else None

        if protocol_version is not None and protocol_version < MIN_PROTOCOL_VERSION:
            raise ProtocolIncompatible(
                f"Gateway protocol version ({protocol_version}) is too old. "
                f"Client requires at least protocol version {MIN_PROTOCOL_VERSION}. Please update the gateway."
            )
        if min_protocol_version is not None and min_protocol_version > PROTOCOL_VERSION:
            raise ProtocolIncompatible(
                f"Client protocol version ({PROTOCOL_VERSION}) is incompatible with gateway (requires at least {min_protocol_version}). "
                "Please update ByteBuddhi."
            )

        return HealthSnapshot(
            status=str(body.get("status", "")),
            service=str(body["service"]) if body.get("service") is not None else None,
            version=str(body["version"]) if body.get("version") is not None else None,
            protocol_version=protocol_version,
            min_protocol_version=min_protocol_version,
        )

    async def readiness(self) -> ReadinessSnapshot:
        response = await self._request(
            "GET",
            "/api/v1/health/ready",
            operation="readiness",
            retry=True,
            accept_statuses={503},
        )
        body = _object(response)
        raw_checks = body.get("checks")
        checks = raw_checks if isinstance(raw_checks, dict) else {}
        return ReadinessSnapshot(
            status=str(body.get("status", "")),
            checks={str(key): str(value) for key, value in checks.items()},
        )

    async def list_projects(self) -> list[ProjectResponse]:
        response = await self._request("GET", "/api/v1/projects", operation="list_projects")
        payload = _json(response)
        if not isinstance(payload, list):
            raise MalformedResponse("Gateway returned an unexpected project list")
        try:
            return [ProjectResponse.model_validate(item) for item in payload]
        except ValidationError as exc:
            raise MalformedResponse("Gateway returned an unexpected project list") from exc

    async def get_project(self, project_id: UUID) -> ProjectResponse:
        response = await self._request("GET", f"/api/v1/projects/{project_id}", operation="get_project")
        try:
            return ProjectResponse.model_validate(_object(response))
        except ValidationError as exc:
            raise MalformedResponse("Gateway returned an unexpected project") from exc

    async def resolve_local_project(self, local_path: str) -> UUID:
        if not self.local_gateway:
            raise InvalidRequest(
                "--cwd is only valid against the local gateway. A remote gateway cannot use paths from this machine."
            )
        response = await self._request(
            "POST",
            "/api/v1/projects/resolve-path",
            operation="resolve_local_project",
            json_body={"local_path": local_path},
        )
        body = _object(response)
        try:
            return UUID(str(body["project_id"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise MalformedResponse("Gateway returned an unexpected project id") from exc

    async def list_models(self) -> ModelCatalogResponse:
        response = await self._request("GET", "/api/v1/models", operation="list_models")
        try:
            return ModelCatalogResponse.model_validate(_object(response))
        except ValidationError as exc:
            raise MalformedResponse("Gateway returned an unexpected model catalog") from exc

    async def create_conversation(
        self,
        *,
        project_id: UUID | None = None,
        title: str | None = None,
    ) -> ConversationResponse:
        body: dict[str, Any] = {"project_id": str(project_id) if project_id else None, "title": title}
        response = await self._request(
            "POST",
            "/api/v1/chat/conversations",
            operation="create_conversation",
            json_body=body,
        )
        try:
            return ConversationResponse.model_validate(_object(response))
        except ValidationError as exc:
            raise MalformedResponse("Gateway returned an unexpected conversation") from exc

    async def list_conversations(self) -> list[ConversationResponse]:
        response = await self._request("GET", "/api/v1/chat/conversations", operation="list_conversations")
        payload = _json(response)
        if not isinstance(payload, list):
            raise MalformedResponse("Gateway returned an unexpected conversation list")
        try:
            return [ConversationResponse.model_validate(item) for item in payload]
        except ValidationError as exc:
            raise MalformedResponse("Gateway returned an unexpected conversation list") from exc

    async def list_messages(self, conversation_id: UUID, *, limit: int = 200) -> list[MessageResponse]:
        response = await self._request(
            "GET",
            f"/api/v1/chat/conversations/{conversation_id}/messages?limit={limit}",
            operation="list_messages",
        )
        payload = _json(response)
        if not isinstance(payload, list):
            raise MalformedResponse("Gateway returned an unexpected message list")
        try:
            return [MessageResponse.model_validate(item) for item in payload]
        except ValidationError as exc:
            raise MalformedResponse("Gateway returned an unexpected message list") from exc

    async def read_run_socket(self, run_id: str, *, after_sequence: int = 0) -> AsyncIterator[dict[str, Any]]:
        """One WebSocket attempt. Reconnect and catch-up belong to the caller."""
        if not _valid_run_id(run_id) or after_sequence < 0:
            raise InvalidRequest("Run id is invalid")
        async for raw in self._read_socket(run_id, after_sequence):
            item = _event_dict(raw)
            if item is not None:
                yield item

    async def create_run(
        self,
        *,
        prompt: str,
        project_id: UUID | None = None,
        conversation_id: UUID | None = None,
        model_provider: str | None = None,
        model_name: str | None = None,
        idempotency_key: str | None = None,
    ) -> RunCreateResponse:
        """Queue one run. This POST is never retried."""
        payload: dict[str, Any] = {
            "prompt": prompt,
            "project_id": str(project_id) if project_id else None,
            "conversation_id": str(conversation_id) if conversation_id else None,
        }
        if model_provider or model_name:
            payload["model"] = {"provider": model_provider, "model": model_name}
        key = idempotency_key or str(uuid4())
        response = await self._request(
            "POST",
            "/api/v1/runs",
            operation="create_run",
            json_body=payload,
            timeout=api_timeout(),
            retry=False,
            extra_headers={"Idempotency-Key": key},
        )
        try:
            return RunCreateResponse.model_validate(_object(response))
        except ValidationError as exc:
            raise MalformedResponse("Gateway returned an unexpected run result") from exc

    async def get_run(self, run_id: str) -> RunResponse:
        if not _valid_run_id(run_id):
            raise InvalidRequest("Run id is invalid")
        response = await self._request("GET", f"/api/v1/runs/{run_id}", operation="get_run")
        try:
            return RunResponse.model_validate(_object(response))
        except ValidationError as exc:
            raise MalformedResponse("Gateway returned an unexpected run") from exc

    async def get_run_events(self, run_id: str, *, after_sequence: int = 0, limit: int = 200) -> RunEventPage:
        if not _valid_run_id(run_id) or after_sequence < 0:
            raise InvalidRequest("Run event cursor is invalid")
        response = await self._request(
            "GET",
            f"/api/v1/runs/{run_id}/events?after_sequence={after_sequence}&limit={limit}",
            operation="get_run_events",
        )
        try:
            return RunEventPage.model_validate(_object(response))
        except ValidationError as exc:
            raise MalformedResponse("Gateway returned an unexpected event page") from exc

    async def stream_run(self, run_id: str, *, after_sequence: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Replay, then follow live events. Reconnects do not create another run."""
        if not _valid_run_id(run_id):
            raise InvalidRequest("Run id is invalid")
        tracker = SequenceTracker(after_sequence)
        failures = 0
        while True:
            try:
                async for event in self._read_socket(run_id, tracker.last_sequence):
                    item = _event_dict(event)
                    if item is None:
                        continue
                    try:
                        state = tracker.observe(int(item["sequence"]))
                    except SequenceGap:
                        async for caught in self._catch_up(run_id, tracker):
                            yield caught
                            if str(caught.get("type")) in _TERMINAL_RUN_EVENTS:
                                return
                        continue
                    if state == "duplicate":
                        continue
                    yield item
                    if str(item.get("type")) in _TERMINAL_RUN_EVENTS:
                        return
                raise GatewayUnavailable(self._unavailable_message("stream_run"))
            except (GatewayUnavailable, GatewayTimeout):
                failures += 1
                if failures > _STREAM_RECONNECTS:
                    raise
                await self._backoff(failures)

    async def _catch_up(self, run_id: str, tracker: SequenceTracker):
        while True:
            page = await self.get_run_events(run_id, after_sequence=tracker.last_sequence)
            if not page.events:
                return
            for event in page.events:
                tracker.observe(event.sequence)
                yield event.model_dump()
                if event.type in _TERMINAL_RUN_EVENTS:
                    return
            if not page.has_more:
                return

    async def _read_socket(self, run_id: str, after_sequence: int):
        url = _websocket_url(self.base_url, f"/api/v1/runs/{run_id}/stream?after_sequence={after_sequence}")
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            async with websockets.connect(
                url,
                additional_headers=headers,
                proxy=None,
                open_timeout=CONNECT_TIMEOUT_SECONDS,
                max_size=1_048_576,
                ping_interval=20,
            ) as socket:
                while True:
                    raw = await asyncio.wait_for(socket.recv(), timeout=STREAM_READ_TIMEOUT_SECONDS)
                    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                    yield json.loads(text)
        except TimeoutError as exc:
            raise GatewayTimeout(f"Timed out while streaming run {run_id}") from exc
        except websockets.ConnectionClosed:
            return
        except (OSError, websockets.WebSocketException) as exc:
            raise GatewayUnavailable(self._unavailable_message("stream_run")) from exc

    async def send_message(
        self,
        conversation_id: UUID,
        content: str,
        *,
        model_provider: str | None = None,
        model_name: str | None = None,
    ) -> MessageStreamResult:
        """Consume the current chat SSE body once. Not retried."""
        payload: dict[str, Any] = {"content": content}
        if model_provider and model_name:
            payload["model"] = {"provider": model_provider, "model": model_name}
        response = await self._request(
            "POST",
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            operation="send_message",
            json_body=payload,
            timeout=stream_timeout(),
            retry=False,
        )
        return _parse_sse(response.text, conversation_id=str(conversation_id))

    async def cancel_run(self, run_id: str) -> CancelAck:
        if not _valid_run_id(run_id):
            raise InvalidRequest("Run id is invalid")
        response = await self._request(
            "POST",
            f"/api/v1/runs/{run_id}/cancel",
            operation="cancel_run",
            retry=False,
        )
        body = _object(response)
        return CancelAck(run_id=str(body.get("run_id") or run_id), status=str(body.get("status") or ""))

    async def submit_approval(self, run_id: str, *, action: str, decision: str) -> None:
        if not _valid_run_id(run_id):
            raise InvalidRequest("Run id is invalid")
        await self._request(
            "POST",
            f"/api/v1/runs/{run_id}/approval",
            operation="submit_approval",
            json_body={"action": action, "decision": decision},
            retry=False,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        json_body: dict[str, Any] | None = None,
        timeout: httpx.Timeout | None = None,
        retry: bool = False,
        accept_statuses: set[int] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        if method.upper() != "GET":
            retry = False
        attempts = SAFE_RETRY_ATTEMPTS if retry else 1
        request_id = str(uuid4())
        headers = self._headers(request_id)
        if extra_headers:
            headers.update(extra_headers)
        url = self.base_url + path
        accepted = accept_statuses or set()
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                response = await self._http.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                    timeout=timeout or api_timeout(),
                )
            except httpx.TimeoutException as exc:
                if attempt >= attempts:
                    self._log_failure(
                        operation=operation,
                        method=method,
                        path=path,
                        request_id=request_id,
                        attempt=attempt,
                        duration_ms=_elapsed_ms(started),
                        error_type=type(exc).__name__,
                    )
                    raise GatewayTimeout(
                        self._diagnostic(f"Timed out waiting for the gateway during {operation}", path)
                    ) from None
                await self._backoff(attempt)
                continue
            except httpx.TransportError as exc:
                if attempt >= attempts:
                    self._log_failure(
                        operation=operation,
                        method=method,
                        path=path,
                        request_id=request_id,
                        attempt=attempt,
                        duration_ms=_elapsed_ms(started),
                        error_type=type(exc).__name__,
                    )
                    raise GatewayUnavailable(self._unavailable_message(operation)) from None
                await self._backoff(attempt)
                continue
            if response.status_code >= 400 and response.status_code not in accepted:
                if retry and response.status_code >= 500 and attempt < attempts:
                    await self._backoff(attempt)
                    continue
                self._log_failure(
                    operation=operation,
                    method=method,
                    path=path,
                    request_id=request_id,
                    attempt=attempt,
                    duration_ms=_elapsed_ms(started),
                    status_code=response.status_code,
                    error_type="http_status",
                )
                raise self._map_status(response, operation=operation, path=path)
            return response
        raise GatewayUnavailable(self._unavailable_message(operation))

    def _headers(self, request_id: str) -> dict[str, str]:
        headers = {"Accept": "application/json", "X-Request-ID": request_id}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _map_status(self, response: httpx.Response, *, operation: str, path: str) -> GatewayError:
        message = _safe_detail(response, self._token)
        if self.debug:
            message = f"{message} ({operation} {path} HTTP {response.status_code})"
        error_type = _STATUS_ERRORS.get(response.status_code)
        if error_type is AuthenticationRequired:
            return AuthenticationRequired("Authentication required or expired. Run bytebuddhi login.")
        if error_type is not None and response.status_code != 401:
            if response.status_code == 403:
                return AuthorizationDenied(message or "Authorization denied")
            return error_type(message or error_type.__name__)
        if response.status_code >= 500:
            public = "The gateway failed to complete the request."
            if self.debug and message:
                public = f"{public} {message}"
            return GatewayServerError(public)
        return GatewayServerError(message or f"Gateway request failed during {operation}")

    def _diagnostic(self, message: str, path: str) -> str:
        if self.debug:
            return f"{message} ({path})"
        return message

    def _unavailable_message(self, operation: str) -> str:
        return (
            f"Gateway is not reachable at {self.base_url} during {operation}. "
            "Start it with `bytebuddhi gateway start`, or pass --no-start-gateway if it should already be running. "
            "ByteBuddhi will not switch to embedded mode."
        )

    def _log_failure(
        self,
        *,
        operation: str,
        method: str,
        path: str,
        request_id: str,
        attempt: int,
        duration_ms: int,
        error_type: str,
        status_code: int | None = None,
    ) -> None:
        logger.warning(
            "gateway_client_request_failed",
            operation=operation,
            command=f"{method} {path}",
            method=method,
            path=path,
            host=_host_of(self.base_url),
            status_code=status_code,
            duration_ms=duration_ms,
            request_id=request_id,
            attempt=attempt,
            error_type=error_type,
        )

    async def _backoff(self, attempt: int) -> None:
        base = min(0.25 * (2 ** (attempt - 1)), 2.0)
        await self._sleep(base + random.uniform(0, 0.1))


async def probe_gateway(url: str, *, timeout: httpx.Timeout | None = None) -> ProbeResult:
    """Single-attempt liveness and readiness probe. The manager loop bounds retries."""
    origin = url.rstrip("/")
    chosen = timeout or probe_timeout()
    try:
        async with httpx.AsyncClient(timeout=chosen, follow_redirects=False, trust_env=False) as client:
            live_response = await client.get(origin + "/api/v1/health/live")
            ready_response = await client.get(origin + "/api/v1/health/ready")
    except httpx.TimeoutException:
        return ProbeResult(False, False, False, False, detail="timeout")
    except httpx.TransportError as exc:
        return ProbeResult(False, False, False, False, detail=type(exc).__name__)
    live_body = _optional_object(live_response)
    ready_body = _optional_object(ready_response)
    bytebuddhi = _is_bytebuddhi(live_body) or _is_bytebuddhi(ready_body)
    version = live_body.get("version")
    return ProbeResult(
        reachable=True,
        live=live_response.status_code == 200 and str(live_body.get("status", "")) == "ok",
        ready=ready_response.status_code == 200 and str(ready_body.get("status", "")) == "ready",
        bytebuddhi=bytebuddhi,
        version=str(version) if version is not None else None,
        detail=f"live={live_response.status_code} ready={ready_response.status_code}",
    )


def _is_bytebuddhi(body: dict[str, Any]) -> bool:
    service = str(body.get("service", ""))
    name = str(body.get("name", ""))
    return service == "ByteBuddhi API" or name == "ByteBuddhi"


def _event_dict(event: object) -> dict[str, Any] | None:
    if not isinstance(event, dict) or event.get("type") == "ping" or "sequence" not in event:
        return None
    return event


def _websocket_url(base: str, path: str) -> str:
    if base.startswith("https://"):
        return "wss://" + base.removeprefix("https://") + path
    if base.startswith("http://"):
        return "ws://" + base.removeprefix("http://") + path
    return "ws://" + base + path


def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.netloc


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise MalformedResponse("Gateway returned a response that was not valid JSON") from exc


def _object(response: httpx.Response) -> dict[str, Any]:
    payload = _json(response)
    if not isinstance(payload, dict):
        raise MalformedResponse("Gateway returned an unexpected response")
    return payload


def _optional_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _safe_detail(response: httpx.Response, token: str | None) -> str:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return "Gateway request failed"
    message = ""
    if isinstance(payload, dict):
        raw = payload.get("message") or payload.get("detail") or payload.get("error")
        if isinstance(raw, str):
            message = raw
        elif isinstance(raw, list):
            parts: list[str] = []
            for item in raw:
                if isinstance(item, dict) and item.get("msg"):
                    parts.append(str(item["msg"]))
            message = "; ".join(parts)
    if not message:
        return "Gateway request failed"
    secrets = (token,) if token else ()
    return redact_secrets(message, *secrets)[:500]


def _valid_run_id(run_id: str) -> bool:
    import re

    return re.fullmatch(_RUN_ID_RE_RAW, run_id) is not None


def _parse_sse(body: str, *, conversation_id: str) -> MessageStreamResult:
    event_name = "message"
    data_lines: list[str] = []
    events: list[tuple[str, str]] = []

    def _flush() -> None:
        nonlocal event_name, data_lines
        if data_lines:
            events.append((event_name, "\n".join(data_lines)))
        event_name = "message"
        data_lines = []

    for line in body.splitlines():
        if line == "":
            _flush()
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    _flush()
    content: list[str] = []
    errors: list[str] = []
    run_id: str | None = None
    status = "completed"
    for name, data in events:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("run_id"):
            run_id = str(payload["run_id"])
        if name == "content" and payload.get("content"):
            content.append(str(payload["content"]))
        elif name in {"error", "cancelled"}:
            status = "cancelled" if name == "cancelled" else "failed"
            if payload.get("error"):
                errors.append(redact_secrets(str(payload["error"])))
    if not events:
        raise MalformedResponse("Gateway returned an unexpected message stream")
    return MessageStreamResult(
        run_id=run_id,
        conversation_id=conversation_id,
        content="".join(content),
        status=status,
        errors=tuple(errors),
    )
