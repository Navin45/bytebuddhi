"""Anthropic LLM provider implementation.

This module provides the concrete implementation of the LLMProvider interface
using Anthropic's Claude API. It supports chat completions with streaming.
"""

from typing import AsyncIterator, Dict, List, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.application.ports.output.llm.llm_provider import LLMProvider
from app.infrastructure.config.logger import get_logger
from app.infrastructure.config.settings import settings

logger = get_logger(__name__)


class AnthropicProvider(LLMProvider):
    """Anthropic implementation of LLMProvider.
    
    This class provides integration with Anthropic's Claude API for chat
    completions. Note that Anthropic does not provide embedding models,
    so embedding methods will raise NotImplementedError.
    
    Attributes:
        chat_model: LangChain ChatAnthropic instance for completions
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        """Initialize Anthropic provider.
        
        Args:
            api_key: Anthropic API key (defaults to settings.anthropic_api_key)
            model: Model name (defaults to settings.anthropic_model)
        """
        self.api_key = api_key or settings.anthropic_api_key
        self.model_name = model or settings.anthropic_model
        
        if not self.api_key:
            raise ValueError("Anthropic API key is required")
        
        # Initialize chat model
        self.chat_model = ChatAnthropic(
            api_key=self.api_key,
            model=self.model_name,
            temperature=0.7,
            streaming=True,
        )
        
        logger.info("Anthropic provider initialized", model=self.model_name)

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate a chat completion.
        
        Args:
            messages: List of message dicts with 'role' and 'content' keys
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens to generate
            
        Returns:
            str: Generated response content
        """
        try:
            # Convert to LangChain message format
            lc_messages = self._convert_messages(messages)
            
            # Update temperature if different from default
            if temperature != 0.7:
                self.chat_model.temperature = temperature
            
            # Update max_tokens if provided
            # Claude requires max_tokens to be set
            if max_tokens is not None:
                self.chat_model.max_tokens = max_tokens
            elif not hasattr(self.chat_model, 'max_tokens') or self.chat_model.max_tokens is None:
                self.chat_model.max_tokens = 4096
            
            # Generate response
            response = await self.chat_model.ainvoke(lc_messages)
            
            return response.content
        except Exception as e:
            logger.error("Anthropic generation failed", error=str(e))
            raise

    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """Generate a streaming chat completion.
        
        Yields response content as it's generated, enabling real-time
        streaming to the client.
        
        Args:
            messages: List of message dicts with 'role' and 'content' keys
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens to generate
            
        Yields:
            str: Chunks of generated content
        """
        try:
            # Convert to LangChain message format
            lc_messages = self._convert_messages(messages)
            
            # Update temperature if different from default
            if temperature != 0.7:
                self.chat_model.temperature = temperature
            
            # Update max_tokens if provided
            if max_tokens is not None:
                self.chat_model.max_tokens = max_tokens
            elif not hasattr(self.chat_model, 'max_tokens') or self.chat_model.max_tokens is None:
                self.chat_model.max_tokens = 4096
            
            # Stream response
            async for chunk in self.chat_model.astream(lc_messages):
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            logger.error("Anthropic streaming failed", error=str(e))
            raise

    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding vector for text.
        
        Note: Anthropic does not provide embedding models.
        Use OpenAI provider for embeddings.
        
        Raises:
            NotImplementedError: Anthropic does not support embeddings
        """
        raise NotImplementedError(
            "Anthropic does not provide embedding models. Use OpenAI provider for embeddings."
        )

    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for multiple texts.
        
        Note: Anthropic does not provide embedding models.
        Use OpenAI provider for embeddings.
        
        Raises:
            NotImplementedError: Anthropic does not support embeddings
        """
        raise NotImplementedError(
            "Anthropic does not provide embedding models. Use OpenAI provider for embeddings."
        )

    @staticmethod
    def _convert_messages(messages: List[Dict[str, str]]) -> List:
        """Convert message dicts to LangChain message objects.
        
        Args:
            messages: List of message dicts with 'role' and 'content' keys
            
        Returns:
            List: List of LangChain message objects
        """
        lc_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
            else:  # user or any other role
                lc_messages.append(HumanMessage(content=content))
        
        return lc_messages
