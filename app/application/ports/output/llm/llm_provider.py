from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class LLMProvider(ABC):
    """Abstract LLM provider."""

    model_name: str = ""

    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs,
    ) -> str:
        """Generate a response from the LLM."""
        pass

    @abstractmethod
    def generate_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a response from the LLM."""
        pass

    async def stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs,
    ) -> AsyncIterator[str]:
        """Alias for generate_stream."""
        async for chunk in self.generate_stream(messages, temperature, max_tokens, **kwargs):
            yield chunk

    @abstractmethod
    async def generate_embedding(self, text: str) -> list[float]:
        """Generate embedding for text."""
        pass

    async def get_embedding(self, text: str) -> list[float]:
        """Alias for generate_embedding."""
        return await self.generate_embedding(text)

    async def create_embedding(self, text: str) -> list[float]:
        """Alias for generate_embedding."""
        return await self.generate_embedding(text)

    @abstractmethod
    async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        pass

    async def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Alias for generate_embeddings."""
        return await self.generate_embeddings(texts)
