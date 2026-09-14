"""Normalize LangChain chat results and provider errors inside adapters only."""

from typing import Any

from app.application.agent.errors import ModelCallError
from app.application.ports.output.llm.model_gateway import ModelResponse, ModelStreamChunk, TokenUsage
from app.application.tools.definition import ToolCall


def parse_chat_response(response: Any, *, provider: str, model: str) -> ModelResponse:
    tool_calls: list[ToolCall] = []
    if hasattr(response, "tool_calls") and response.tool_calls:
        for tc in response.tool_calls:
            tool_calls.append(
                ToolCall(
                    id=str(tc.get("id", "")),
                    name=tc.get("name", ""),
                    arguments=tc.get("args", {}),
                )
            )

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

    content = response.content if isinstance(response.content, str) else str(response.content)
    return ModelResponse(
        content=content,
        tool_calls=tool_calls,
        usage=usage,
        model=model,
        provider=provider,
        finish_reason=finish_reason,
    )


def parse_stream_chunk(chunk: Any, *, provider: str, model: str) -> ModelStreamChunk:
    tool_calls: list[ToolCall] = []
    if hasattr(chunk, "tool_calls") and chunk.tool_calls:
        for tc in chunk.tool_calls:
            tool_calls.append(
                ToolCall(
                    id=str(tc.get("id", "")),
                    name=tc.get("name", ""),
                    arguments=tc.get("args", {}),
                )
            )
    content = chunk.content if isinstance(getattr(chunk, "content", None), str) else None
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
