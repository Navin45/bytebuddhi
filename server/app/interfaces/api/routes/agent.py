"""Agent feedback API route.

This module provides an endpoint for users to submit feedback
on agent responses, which is logged to LangSmith for quality tracking.
"""

from fastapi import APIRouter, HTTPException, status

from app.infrastructure.config.logger import get_logger
from app.infrastructure.monitoring import is_langsmith_enabled, log_agent_feedback
from app.interfaces.api.schemas.agent_schema import (
    AgentFeedbackRequest,
    AgentFeedbackResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["Agent"])


@router.post("/feedback", response_model=AgentFeedbackResponse)
async def submit_feedback(request: AgentFeedbackRequest):
    """Submit feedback for an agent response.
    
    This endpoint allows users to provide feedback on agent responses,
    which is logged to LangSmith for quality tracking and improvement.
    
    Args:
        request: Feedback data including run_id and score
        
    Returns:
        AgentFeedbackResponse: Feedback submission status
        
    Raises:
        HTTPException: If LangSmith is not configured
    """
    if not is_langsmith_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LangSmith integration not configured",
        )
    
    try:
        log_agent_feedback(
            run_id=request.run_id,
            score=request.score,
            comment=request.comment,
        )
        
        logger.info(
            "Agent feedback submitted",
            run_id=request.run_id,
            score=request.score,
        )
        
        return AgentFeedbackResponse(
            success=True,
            message="Feedback recorded successfully",
        )
        
    except Exception as e:
        logger.error("Failed to submit feedback", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record feedback",
        )
