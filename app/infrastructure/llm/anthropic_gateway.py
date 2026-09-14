"""Anthropic chat adapter implementing ModelGateway."""

from collections.abc import AsyncIterator
from typing import Any

from langchain_anthropic import ChatAnthropic

from app.application.ports.output.llm.model_gateway import (
    ModelGateway,
    ModelResponse,
    ModelStreamChunk,
)
from app.infrastructure.config.logger import get_logger
from app.infrastructure.config.settings import settings
from app.infrastructure.llm.langchain_support import parse_chat_response, parse_stream_chunk, wrap_provider_error
from app.infrastructure.llm.message_converter import convert_dict_messages_to_langchain

logger = get_logger(__name__)


class AnthropicModelGateway(ModelGateway):
    """Anthropic adapter. Credentials stay on this object, never in requests."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        chat_model: ChatAnthropic | None = None,
    ):
        self.api_key = api_key or settings.anthropic_api_key
        self.model_name = model or settings.anthropic_model
        self.provider_id = "anthropic"
        self._clients: dict[str, Any] = {}

        if chat_model is not None:
            self.chat_model = chat_model
            self._clients[self.model_name] = chat_model
        else:
            if not self.api_key:
                raise ValueError("Anthropic API key is required for AnthropicModelGateway")
            self.chat_model = self._make_client(self.model_name)

    def _make_client(self, model_name: str) -> ChatAnthropic:
        return ChatAnthropic(
            api_key=self.api_key,
            model=model_name,
            temperature=0.7,
            streaming=True,
            max_tokens=4096,
        )

    def _client_for(self, model_name: str | None) -> Any:
        name = model_name or self.model_name
        cached = self._clients.get(name)
        if cached is not None:
            return cached
        if name == self.model_name:
            self._clients[name] = self.chat_model
            return self.chat_model
        if len(self._clients) >= 8:
            self._clients.pop(next(iter(self._clients)))
        client = self._make_client(name)
        self._clients[name] = client
        return client

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        model_name = str(kwargs.get("model") or self.model_name)
        provider = str(kwargs.get("provider") or self.provider_id)
        try:
            lc_messages = convert_dict_messages_to_langchain(messages)
            model: Any = self._client_for(model_name)
            if tools:
                model = model.bind_tools(tools)
            invoke_kwargs: dict[str, Any] = {}
            if max_tokens is not None:
                invoke_kwargs["max_tokens"] = max_tokens
            response = await model.ainvoke(lc_messages, **invoke_kwargs)
            return parse_chat_response(response, provider=provider, model=model_name)
        except Exception as e:
            logger.error("Model adapter call failed", provider=provider, model=model_name, error=str(e))
            raise wrap_provider_error(e, provider=provider, model=model_name) from e

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ModelStreamChunk]:
        model_name = str(kwargs.get("model") or self.model_name)
        provider = str(kwargs.get("provider") or self.provider_id)
        try:
            lc_messages = convert_dict_messages_to_langchain(messages)
            model: Any = self._client_for(model_name)
            if tools:
                model = model.bind_tools(tools)
            async for chunk in model.astream(lc_messages):
                yield parse_stream_chunk(chunk, provider=provider, model=model_name)
        except Exception as e:
            logger.error("Model adapter stream failed", provider=provider, model=model_name, error=str(e))
            raise wrap_provider_error(e, provider=provider, model=model_name) from e
