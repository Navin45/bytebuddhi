"""Routing ModelGateway: catalog authorization then adapter dispatch."""

from collections.abc import AsyncIterator
from typing import Any

from app.application.ports.output.llm.model_catalog import ModelCatalog, ProviderRegistry
from app.application.ports.output.llm.model_gateway import ModelResponse, ModelStreamChunk


class RoutingModelGateway:
    """Single LLM boundary for AgentRuntime. Provider SDKs stay behind adapters."""

    def __init__(self, catalog: ModelCatalog, registry: ProviderRegistry) -> None:
        self._catalog = catalog
        self._registry = registry

    @property
    def catalog(self) -> ModelCatalog:
        return self._catalog

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        descriptor = self._catalog.resolve(kwargs.get("provider"), kwargs.get("model"))
        adapter = self._registry.get(descriptor.provider)
        output_cap = descriptor.max_output_tokens
        effective_max = max_tokens
        if output_cap is not None and (effective_max is None or effective_max > output_cap):
            effective_max = output_cap
        response = await adapter.generate(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=effective_max,
            provider=descriptor.provider,
            model=descriptor.model,
        )
        if response.provider is None:
            response.provider = descriptor.provider
        if response.model is None:
            response.model = descriptor.model
        return response

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ModelStreamChunk]:
        descriptor = self._catalog.resolve(kwargs.get("provider"), kwargs.get("model"))
        adapter = self._registry.get(descriptor.provider)
        async for chunk in adapter.stream(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            provider=descriptor.provider,
            model=descriptor.model,
        ):
            if chunk.provider is None:
                chunk.provider = descriptor.provider
            if chunk.model is None:
                chunk.model = descriptor.model
            yield chunk
