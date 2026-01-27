"""LangSmith integration for agent tracing and monitoring.

This module configures LangSmith for tracing LangGraph agent execution,
enabling debugging, performance monitoring, and conversation analysis.
"""

import os
from typing import Optional

from langsmith import Client

from app.infrastructure.config.logger import get_logger
from app.infrastructure.config.settings import settings

logger = get_logger(__name__)


class LangSmithConfig:
    """LangSmith configuration and client management.
    
    This class handles LangSmith setup, including environment variable
    configuration and client initialization for agent tracing.
    
    Attributes:
        enabled: Whether LangSmith tracing is enabled
        client: LangSmith client instance
        project_name: Project name for organizing traces
    """

    def __init__(self):
        """Initialize LangSmith configuration."""
        self.enabled = False
        self.client: Optional[Client] = None
        self.project_name = settings.langchain_project
        
        self._configure()

    def _configure(self) -> None:
        """Configure LangSmith environment variables and client.
        
        Sets up LangSmith tracing by configuring environment variables
        and initializing the client if an API key is provided.
        """
        # Check if API key is available
        if not settings.langchain_api_key:
            logger.warning("LangSmith API key not configured, tracing disabled")
            return

        try:
            # Set environment variables for LangChain tracing
            os.environ["LANGCHAIN_TRACING_V2"] = str(settings.langchain_tracing_v2).lower()
            os.environ["LANGCHAIN_ENDPOINT"] = settings.langchain_endpoint
            os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
            os.environ["LANGCHAIN_PROJECT"] = self.project_name

            # Initialize client
            self.client = Client(
                api_url=settings.langchain_endpoint,
                api_key=settings.langchain_api_key,
            )

            self.enabled = True
            logger.info(
                "LangSmith tracing enabled",
                project=self.project_name,
                endpoint=settings.langchain_endpoint,
            )

        except Exception as e:
            logger.error("Failed to configure LangSmith", error=str(e))
            self.enabled = False

    def is_enabled(self) -> bool:
        """Check if LangSmith tracing is enabled.
        
        Returns:
            bool: True if tracing is enabled and configured
        """
        return self.enabled

    def get_client(self) -> Optional[Client]:
        """Get LangSmith client instance.
        
        Returns:
            Optional[Client]: LangSmith client or None if not configured
        """
        return self.client

    def create_run_url(self, run_id: str) -> str:
        """Create URL to view a specific run in LangSmith.
        
        Args:
            run_id: LangSmith run identifier
            
        Returns:
            str: URL to view the run in LangSmith UI
        """
        if not self.enabled:
            return ""
        
        return f"{settings.langchain_endpoint}/o/default/projects/p/{self.project_name}/r/{run_id}"

    def log_feedback(
        self,
        run_id: str,
        score: float,
        comment: Optional[str] = None,
    ) -> None:
        """Log user feedback for a run.
        
        Records user feedback (thumbs up/down, ratings) for an agent
        run, enabling quality tracking and model improvement.
        
        Args:
            run_id: LangSmith run identifier
            score: Feedback score (0.0 to 1.0, or -1.0 to 1.0)
            comment: Optional feedback comment
        """
        if not self.enabled or not self.client:
            logger.warning("LangSmith not enabled, cannot log feedback")
            return

        try:
            self.client.create_feedback(
                run_id=run_id,
                key="user_feedback",
                score=score,
                comment=comment,
            )
            logger.info("Feedback logged", run_id=run_id, score=score)

        except Exception as e:
            logger.error("Failed to log feedback", error=str(e), run_id=run_id)


# Global LangSmith configuration instance
langsmith_config = LangSmithConfig()


def get_langsmith_client() -> Optional[Client]:
    """Get the global LangSmith client.
    
    Returns:
        Optional[Client]: LangSmith client or None if not configured
    """
    return langsmith_config.get_client()


def is_langsmith_enabled() -> bool:
    """Check if LangSmith tracing is enabled.
    
    Returns:
        bool: True if LangSmith is configured and enabled
    """
    return langsmith_config.is_enabled()


def log_agent_feedback(run_id: str, score: float, comment: Optional[str] = None) -> None:
    """Log feedback for an agent run.
    
    Convenience function to log user feedback for agent execution.
    
    Args:
        run_id: LangSmith run identifier
        score: Feedback score (0.0 to 1.0)
        comment: Optional feedback comment
    """
    langsmith_config.log_feedback(run_id, score, comment)


def get_run_url(run_id: str) -> str:
    """Get URL to view a run in LangSmith.
    
    Args:
        run_id: LangSmith run identifier
        
    Returns:
        str: URL to LangSmith run viewer
    """
    return langsmith_config.create_run_url(run_id)
