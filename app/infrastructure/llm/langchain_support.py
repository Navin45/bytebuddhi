"""Normalize LangChain chat results and provider errors inside adapters only."""

from typing import Any

from app.application.agent.errors import ModelCallError
from app.application.ports.output.llm.model_gateway import ModelResponse, ModelStreamChunk, TokenUsage
from app.application.tools.definition import ToolCall


def tool_call_from_mapping(tc: Any) -> ToolCall | None:
    """Normalize one provider tool-call dict.

    Streaming argument deltas often arrive with ``id`` and ``name`` set to ``None``.
    Those must stay blank so the caller can attach the arguments to the open call.
    ``str(None)`` would invent an id and send a nameless function call.
    """
    if not isinstance(tc, dict):
        return None
    raw_id = tc.get("id")
    name = tc.get("name") or ""
    arguments = tc.get("args") if isinstance(tc.get("args"), dict) else {}
    call_id = raw_id if isinstance(raw_id, str) else ""
    if not call_id and not name and not arguments:
        return None
    return ToolCall(id=call_id, name=name, arguments=arguments)


def message_text(content: Any) -> str | None:
    """Read assistant text from a string or a Responses API content block list."""
    if isinstance(content, str):
        return content or None
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        block_type = block.get("type")
        if isinstance(text, str) and block_type in {None, "text", "output_text"}:
            parts.append(text)
    return "".join(parts) or None


def parse_chat_response(response: Any, *, provider: str, model: str) -> ModelResponse:
    tool_calls: list[ToolCall] = []
    if hasattr(response, "tool_calls") and response.tool_calls:
        for tc in response.tool_calls:
            parsed = tool_call_from_mapping(tc)
            if parsed is not None:
                tool_calls.append(parsed)

    usage: TokenUsage | None = None
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        usage = TokenUsage(
            prompt_tokens=response.usage_metadata.get("input_tokens", 0),
            completion_tokens=response.usage_metadata.get("output_tokens", 0),
            total_tokens=response.usage_metadata.get("total_tokens", 0),
        )

    metadata = response.response_metadata if hasattr(response, "response_metadata") else None
    finish_reason = None
    if isinstance(metadata, dict):
        finish_reason = metadata.get("finish_reason") or metadata.get("stop_reason")

    content = message_text(getattr(response, "content", None))
    return ModelResponse(
        content=content,
        tool_calls=tool_calls,
        usage=usage,
        model=model,
        provider=provider,
        finish_reason=finish_reason,
    )


def _tool_call_from_stream_chunk(tc: Any) -> ToolCall | None:
    """Keep the stream index and the raw argument text.

    Responses API argument deltas identify the call by index, not by id.
    Parsing each delta into a dict and attaching it to the latest call
    assigns one tool's query to a different tool.
    """
    if not isinstance(tc, dict):
        return None
    raw_id = tc.get("id")
    name = tc.get("name") or ""
    raw_index = tc.get("index")
    args = tc.get("args")
    fragment = args if isinstance(args, str) else ""
    arguments = args if isinstance(args, dict) else {}
    call_id = raw_id if isinstance(raw_id, str) else ""
    index = raw_index if isinstance(raw_index, int) else None
    if not call_id and not name and not fragment and not arguments and index is None:
        return None
    return ToolCall(
        id=call_id,
        name=name,
        arguments=arguments,
        index=index,
        arguments_json=fragment,
    )


def parse_stream_chunk(chunk: Any, *, provider: str, model: str) -> ModelStreamChunk:
    tool_calls: list[ToolCall] = []
    raw_chunks = getattr(chunk, "tool_call_chunks", None) or []
    if raw_chunks:
        for tc in raw_chunks:
            parsed = _tool_call_from_stream_chunk(tc)
            if parsed is not None:
                tool_calls.append(parsed)
    elif hasattr(chunk, "tool_calls") and chunk.tool_calls:
        for tc in chunk.tool_calls:
            parsed = tool_call_from_mapping(tc)
            if parsed is not None:
                tool_calls.append(parsed)
    content = message_text(getattr(chunk, "content", None))
    return ModelStreamChunk(
        content=content,
        tool_calls=tool_calls,
        provider=provider,
        model=model,
    )


def wrap_provider_error(exc: Exception, *, provider: str, model: str) -> ModelCallError:
    category, retryable = classify_provider_error(exc)
    return ModelCallError(
        message=f"Model provider call failed ({category})",
        details={"provider": provider, "model": model, "category": category},
        is_retryable=retryable,
        cause=exc,
    )


def classify_provider_error(exc: Exception) -> tuple[str, bool]:
    status = _status_code(exc)
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if status in {401, 403} or "authentication" in text or "invalid api key" in text:
        return "authentication_failure", False
    if status == 404 or "not found" in text or "does not exist" in text:
        return "model_unavailable", False
    if status == 429 or "rate limit" in text:
        return "rate_limited", True
    if status is not None and status >= 500:
        return "provider_unavailable", True
    if isinstance(exc, TimeoutError) or "timeout" in name or "timeout" in text or "timed out" in text:
        return "timeout", True
    if "json" in text or "malformed" in text or "invalid response" in text:
        return "response_malformed", False
    if "invalid" in text or status == 400:
        return "invalid_request", False
    return "provider_unavailable", True


def _status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
    return None
