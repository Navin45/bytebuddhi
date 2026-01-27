"""OpenAI LLM provider implementation.

This module provides the concrete implementation of the LLMProvider interface
using OpenAI's API. It supports both chat completions and embeddings generation.
"""

from typing import AsyncIterator, Dict, List, Optional

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.application.ports.output.llm.llm_provider import LLMProvider
from app.infrastructure.config.logger import get_logger
from app.infrastructure.config.settings import settings

logger = get_logger(__name__)


class OpenAIProvider(LLMProvider):
    """OpenAI implementation of LLMProvider.
    
    This class provides integration with OpenAI's API for chat completions
    and embeddings generation. It uses LangChain's OpenAI wrappers for
    consistent interface and built-in retry logic.
    
    Attributes:
        chat_model: LangChain ChatOpenAI instance for completions
        embedding_model: LangChain OpenAIEmbeddings instance for embeddings
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        embedding_model: Optional[str] = None,
    ):
        """Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key (defaults to settings.openai_api_key)
            model: Model name for chat (defaults to settings.openai_model)
            embedding_model: Model for embeddings (defaults to settings.openai_embedding_model)
        """
        self.api_key = api_key or settings.openai_api_key
        self.model_name = model or settings.openai_model
        self.embedding_model_name = embedding_model or settings.openai_embedding_model
        
        if not self.api_key:
            raise ValueError("OpenAI API key is required")
        
        # Initialize chat model
        self.chat_model = ChatOpenAI(
            api_key=self.api_key,
            model=self.model_name,
            temperature=0.7,
            streaming=True,
        )
        
        # Initialize embedding model
        self.embedding_model = OpenAIEmbeddings(
            api_key=self.api_key,
            model=self.embedding_model_name,
        )
        
        logger.info(
            "OpenAI provider initialized",
            model=self.model_name,
            embedding_model=self.embedding_model_name,
        )

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate a chat completion.
        
        Args:
            messages: List of message dicts with 'role' and 'content' keys
            temperature: Sampling temperature (0.0 to 2.0)
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
            if max_tokens is not None:
                self.chat_model.max_tokens = max_tokens
            
            # Generate response
            response = await self.chat_model.ainvoke(lc_messages)
            
            return response.content
        except Exception as e:
            logger.error("OpenAI generation failed", error=str(e))
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
            temperature: Sampling temperature (0.0 to 2.0)
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
            
            # Stream response
            async for chunk in self.chat_model.astream(lc_messages):
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            logger.error("OpenAI streaming failed", error=str(e))
            raise

    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding vector for text.
        
        Args:
            text: Text to embed
            
        Returns:
            List[float]: Embedding vector (1536 dimensions for text-embedding-3-small)
        """
        try:
            embeddings = await self.embedding_model.aembed_documents([text])
            return embeddings[0]
        except Exception as e:
            logger.error("OpenAI embedding generation failed", error=str(e))
            raise

    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for multiple texts.
        
        Batch processing is more efficient than individual calls.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List[List[float]]: List of embedding vectors
        """
        try:
            embeddings = await self.embedding_model.aembed_documents(texts)
            return embeddings
        except Exception as e:
            logger.error("OpenAI batch embedding generation failed", error=str(e))
            raise

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
