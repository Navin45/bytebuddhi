from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, List, Optional


class LLMProvider(ABC):
    """Abstract LLM provider."""

    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> str:
        """Generate a response from the LLM."""
        pass

    @abstractmethod
    async def stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[str]:
        """Stream a response from the LLM."""
        pass

    @abstractmethod
    async def get_embedding(self, text: str) -> List[float]:
        """Get embedding for text."""
        pass

    @abstractmethod
    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings for multiple texts."""
        pass