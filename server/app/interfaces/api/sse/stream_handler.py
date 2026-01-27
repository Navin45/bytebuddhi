"""Server-Sent Events (SSE) stream handler.

This module provides utilities for streaming responses to clients
using Server-Sent Events (SSE). It's used for real-time chat responses
and other streaming operations.
"""

import asyncio
import json
from typing import Any, AsyncIterator, Dict

from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class SSEStreamHandler:
    """Handler for Server-Sent Events streaming.
    
    This class provides methods to format and send data as SSE events,
    following the SSE specification for real-time communication.
    """

    @staticmethod
    def format_sse(data: Dict[str, Any], event: str = "message") -> str:
        """Format data as an SSE event.
        
        Formats data according to the SSE specification:
        - event: event_name
        - data: json_data
        - (blank line)
        
        Args:
            data: Data to send (will be JSON-serialized)
            event: Event type name
            
        Returns:
            str: Formatted SSE event string
        """
        json_data = json.dumps(data)
        return f"event: {event}\ndata: {json_data}\n\n"

    @staticmethod
    async def stream_response(
        content_iterator: AsyncIterator[str],
        metadata: Dict[str, Any] = None,
    ) -> AsyncIterator[str]:
        """Stream LLM response as SSE events.
        
        Takes an async iterator of content chunks and formats them
        as SSE events. Sends metadata at the start and a done event
        at the end.
        
        Args:
            content_iterator: Async iterator yielding content chunks
            metadata: Optional metadata to send at start
            
        Yields:
            str: SSE-formatted event strings
        """
        try:
            # Send metadata if provided
            if metadata:
                yield SSEStreamHandler.format_sse(
                    {"type": "metadata", "metadata": metadata},
                    event="metadata"
                )
            
            # Stream content chunks
            async for chunk in content_iterator:
                if chunk:
                    yield SSEStreamHandler.format_sse(
                        {"type": "content", "content": chunk},
                        event="content"
                    )
                    # Small delay to prevent overwhelming the client
                    await asyncio.sleep(0.01)
            
            # Send done event
            yield SSEStreamHandler.format_sse(
                {"type": "done"},
                event="done"
            )
            
        except Exception as e:
            logger.error("Error during SSE streaming", error=str(e))
            # Send error event
            yield SSEStreamHandler.format_sse(
                {"type": "error", "error": str(e)},
                event="error"
            )

    @staticmethod
    async def stream_with_heartbeat(
        content_iterator: AsyncIterator[str],
        heartbeat_interval: int = 15,
    ) -> AsyncIterator[str]:
        """Stream with periodic heartbeat to keep connection alive.
        
        Some proxies and load balancers close idle connections.
        This method sends periodic heartbeat comments to prevent that.
        
        Args:
            content_iterator: Async iterator yielding content chunks
            heartbeat_interval: Seconds between heartbeats
            
        Yields:
            str: SSE-formatted event strings or heartbeat comments
        """
        last_heartbeat = asyncio.get_event_loop().time()
        
        try:
            async for chunk in content_iterator:
                current_time = asyncio.get_event_loop().time()
                
                # Send heartbeat if needed
                if current_time - last_heartbeat > heartbeat_interval:
                    yield ": heartbeat\n\n"
                    last_heartbeat = current_time
                
                # Send content
                yield chunk
                
        except Exception as e:
            logger.error("Error during heartbeat streaming", error=str(e))
            raise
