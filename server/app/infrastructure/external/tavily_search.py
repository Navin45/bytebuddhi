"""Tavily web search service.

This module provides a service for performing web searches using the Tavily API.
Tavily is optimized for AI applications and provides high-quality search results.
"""

from typing import Any, Dict, List, Optional

from tavily import TavilyClient

from app.infrastructure.config.logger import get_logger
from app.infrastructure.config.settings import settings

logger = get_logger(__name__)


class TavilySearchService:
    """Service for performing web searches using Tavily API.
    
    This service wraps the Tavily API client and provides a clean interface
    for performing web searches with proper error handling and logging.
    
    Attributes:
        client: Tavily API client
        max_results: Maximum number of search results to return
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_results: int = 5,
    ):
        """Initialize the Tavily search service.
        
        Args:
            api_key: Tavily API key (defaults to settings.tavily_api_key)
            max_results: Maximum number of results to return (defaults to 5)
        """
        self.api_key = api_key or settings.tavily_api_key
        self.max_results = max_results or settings.tavily_max_results
        
        if not self.api_key:
            logger.warning("Tavily API key not configured")
            self.client = None
        else:
            self.client = TavilyClient(api_key=self.api_key)
            logger.info("Tavily search service initialized")

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        search_depth: str = "basic",
        include_answer: bool = True,
        include_raw_content: bool = False,
    ) -> Dict[str, Any]:
        """Perform a web search using Tavily.
        
        Args:
            query: Search query string
            max_results: Maximum number of results (overrides default)
            search_depth: Search depth - "basic" or "advanced"
            include_answer: Whether to include AI-generated answer
            include_raw_content: Whether to include raw HTML content
            
        Returns:
            Dict containing search results with the following structure:
            {
                "query": str,
                "answer": str (if include_answer=True),
                "results": List[Dict] with keys: title, url, content, score
                "images": List[str] (URLs of relevant images)
            }
            
        Raises:
            Exception: If Tavily API is not configured or search fails
        """
        if not self.client:
            logger.error("Tavily search attempted without API key")
            raise Exception("Tavily API key not configured")
        
        logger.info(
            "Performing Tavily search",
            query=query,
            max_results=max_results or self.max_results,
            search_depth=search_depth,
        )
        
        try:
            # Perform search
            response = self.client.search(
                query=query,
                max_results=max_results or self.max_results,
                search_depth=search_depth,
                include_answer=include_answer,
                include_raw_content=include_raw_content,
            )
            
            logger.info(
                "Tavily search completed",
                num_results=len(response.get("results", [])),
                has_answer=bool(response.get("answer")),
            )
            
            return response
            
        except Exception as e:
            logger.error("Tavily search failed", error=str(e), query=query)
            raise Exception(f"Web search failed: {str(e)}")

    def format_results_for_context(self, search_response: Dict[str, Any]) -> str:
        """Format search results into a readable context string.
        
        This method converts the Tavily search response into a formatted
        string that can be used as context for LLM prompts.
        
        Args:
            search_response: Response from Tavily search
            
        Returns:
            Formatted string with search results
        """
        formatted = []
        
        # Add answer if available
        if answer := search_response.get("answer"):
            formatted.append(f"**Quick Answer:** {answer}\n")
        
        # Add search results
        results = search_response.get("results", [])
        if results:
            formatted.append("**Web Search Results:**\n")
            for i, result in enumerate(results, 1):
                title = result.get("title", "No title")
                url = result.get("url", "")
                content = result.get("content", "")
                
                formatted.append(f"{i}. **{title}**")
                formatted.append(f"   URL: {url}")
                formatted.append(f"   {content}\n")
        
        return "\n".join(formatted)

    def extract_key_information(self, search_response: Dict[str, Any]) -> List[str]:
        """Extract key information snippets from search results.
        
        Args:
            search_response: Response from Tavily search
            
        Returns:
            List of key information snippets
        """
        snippets = []
        
        # Add answer as first snippet
        if answer := search_response.get("answer"):
            snippets.append(answer)
        
        # Add content from top results
        for result in search_response.get("results", [])[:3]:
            if content := result.get("content"):
                snippets.append(content)
        
        return snippets


# Global instance
tavily_service = TavilySearchService()
