"""LLM provider factory.

This module provides a factory function to create LLM provider instances
based on configuration. It supports OpenAI and Anthropic providers.
"""

from enum import Enum
from typing import Optional

from app.application.ports.output.llm.llm_provider import LLMProvider
from app.infrastructure.config.logger import get_logger
from app.infrastructure.llm.anthropic_provider import AnthropicProvider
from app.infrastructure.llm.openai_provider import OpenAIProvider

logger = get_logger(__name__)


class LLMProviderType(str, Enum):
    """Supported LLM provider types."""
    
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


def create_llm_provider(
    provider_type: LLMProviderType = LLMProviderType.OPENAI,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> LLMProvider:
    """Create an LLM provider instance.
    
    Factory function that creates the appropriate LLM provider based on
    the specified type. Defaults to OpenAI if no type is specified.
    
    Args:
        provider_type: Type of provider to create
        api_key: Optional API key (uses settings if not provided)
        model: Optional model name (uses settings if not provided)
        
    Returns:
        LLMProvider: Configured LLM provider instance
        
    Raises:
        ValueError: If provider_type is not supported
    """
    if provider_type == LLMProviderType.OPENAI:
        logger.info("Creating OpenAI provider")
        return OpenAIProvider(api_key=api_key, model=model)
    elif provider_type == LLMProviderType.ANTHROPIC:
        logger.info("Creating Anthropic provider")
        return AnthropicProvider(api_key=api_key, model=model)
    else:
        raise ValueError(f"Unsupported LLM provider type: {provider_type}")


def create_embedding_provider(
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> LLMProvider:
    """Create an embedding provider instance.
    
    Currently only OpenAI provides embedding models, so this always
    returns an OpenAI provider instance.
    
    Args:
        api_key: Optional OpenAI API key (uses settings if not provided)
        model: Optional embedding model name (uses settings if not provided)
        
    Returns:
        LLMProvider: OpenAI provider configured for embeddings
    """
    logger.info("Creating embedding provider (OpenAI)")
    return OpenAIProvider(api_key=api_key, embedding_model=model)
