"""Conversation context management domain service.

This service manages conversation context, including message history
pruning and context window management for LLM interactions.
"""

from typing import List

from app.domain.models.message import Message


class ConversationContextService:
    """Domain service for conversation context management.
    
    This service handles business logic around conversation context,
    including message selection, context window management, and
    relevance scoring.
    """

    @staticmethod
    def select_messages_for_context(
        messages: List[Message],
        max_tokens: int = 4000,
        avg_tokens_per_message: int = 200,
    ) -> List[Message]:
        """Select messages to include in context window.
        
        Business rule: Keep most recent messages that fit within
        the token limit, always including the last user message.
        
        Args:
            messages: All messages in conversation
            max_tokens: Maximum tokens for context
            avg_tokens_per_message: Average tokens per message
            
        Returns:
            List[Message]: Messages to include in context
        """
        max_messages = max_tokens // avg_tokens_per_message
        
        # Always include at least the last message
        if len(messages) <= max_messages:
            return messages
        
        # Take most recent messages
        return messages[-max_messages:]

    @staticmethod
    def should_summarize_conversation(
        message_count: int,
        threshold: int = 20,
    ) -> bool:
        """Determine if conversation should be summarized.
        
        Business rule: Long conversations should be summarized
        to maintain context quality.
        
        Args:
            message_count: Number of messages in conversation
            threshold: Message count threshold for summarization
            
        Returns:
            bool: True if conversation should be summarized
        """
        return message_count >= threshold

    @staticmethod
    def calculate_message_relevance(
        message: Message,
        current_query: str,
    ) -> float:
        """Calculate relevance score for a message.
        
        Business rule: Recent messages and messages containing
        similar keywords are more relevant.
        
        Args:
            message: Message to score
            current_query: Current user query
            
        Returns:
            float: Relevance score (0.0 to 1.0)
        """
        # Simple keyword-based relevance
        # In production, use embeddings for better relevance
        
        query_words = set(current_query.lower().split())
        message_words = set(message.content.lower().split())
        
        # Calculate word overlap
        overlap = len(query_words & message_words)
        total = len(query_words | message_words)
        
        if total == 0:
            return 0.0
        
        return overlap / total

    @staticmethod
    def format_messages_for_llm(messages: List[Message]) -> List[dict]:
        """Format messages for LLM consumption.
        
        Business rule: Messages must be formatted according to
        LLM provider requirements.
        
        Args:
            messages: Messages to format
            
        Returns:
            List[dict]: Formatted messages for LLM
        """
        formatted = []
        
        for message in messages:
            formatted.append({
                "role": message.role,
                "content": message.content,
            })
        
        return formatted

    @staticmethod
    def estimate_token_count(text: str) -> int:
        """Estimate token count for text.
        
        Business rule: Use rough estimation for token counting
        (actual tokenization is provider-specific).
        
        Args:
            text: Text to estimate
            
        Returns:
            int: Estimated token count
        """
        # Rough estimation: ~4 characters per token
        return len(text) // 4

    @staticmethod
    def prune_old_messages(
        messages: List[Message],
        keep_count: int = 50,
    ) -> List[Message]:
        """Prune old messages from conversation.
        
        Business rule: Keep only the most recent N messages
        to prevent unbounded growth.
        
        Args:
            messages: All messages
            keep_count: Number of messages to keep
            
        Returns:
            List[Message]: Pruned message list
        """
        if len(messages) <= keep_count:
            return messages
        
        # Keep most recent messages
        return messages[-keep_count:]
