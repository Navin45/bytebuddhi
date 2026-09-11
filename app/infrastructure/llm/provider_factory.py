"""LLM provider factory.

This module provides a factory function to create LLM provider instances
based on configuration. It supports OpenAI and Anthropic providers.
"""

from enum import StrEnum

from app.application.ports.output.llm.llm_provider import LLMProvider
from app.application.ports.output.llm.model_gateway import ModelGateway
from app.infrastructure.config.logger import get_logger
from app.infrastructure.llm.anthropic_gateway import AnthropicModelGateway
from app.infrastructure.llm.anthropic_provider import AnthropicProvider
from app.infrastructure.llm.openai_gateway import OpenAIModelGateway
from app.infrastructure.llm.openai_provider import OpenAIProvider

logger = get_logger(__name__)


class LLMProviderType(StrEnum):
    """Supported LLM provider types."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"


def create_llm_provider(
    provider_type: LLMProviderType = LLMProviderType.OPENAI,
    api_key: str | None = None,
    model: str | None = None,
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
    api_key: str | None = None,
    model: str | None = None,
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


def create_model_gateway(
    provider_type: LLMProviderType = LLMProviderType.OPENAI,
    api_key: str | None = None,
    model: str | None = None,
) -> ModelGateway:
    """Create a ModelGateway instance for agent tool execution.

    Args:
        provider_type: Type of provider (openai or anthropic)
        api_key: Optional API key
        model: Optional model name

    Returns:
        ModelGateway: Configured model gateway instance
    """
    if provider_type == LLMProviderType.OPENAI:
        logger.info("Creating OpenAI ModelGateway")
        return OpenAIModelGateway(api_key=api_key, model=model)
    elif provider_type == LLMProviderType.ANTHROPIC:
        logger.info("Creating Anthropic ModelGateway")
        return AnthropicModelGateway(api_key=api_key, model=model)
    else:
        raise ValueError(f"Unsupported ModelGateway provider type: {provider_type}")
