"""API schema for agent feedback.

This module defines Pydantic schemas for submitting feedback
on agent responses, enabling quality tracking and improvement.
"""

from typing import Optional

from pydantic import BaseModel, Field


class AgentFeedbackRequest(BaseModel):
    """Request schema for agent feedback.
    
    This schema is used when users provide feedback on agent
    responses, such as thumbs up/down or detailed ratings.
    
    Attributes:
        run_id: LangSmith run identifier
        score: Feedback score (0.0 to 1.0, where 1.0 is best)
        comment: Optional feedback comment
    """

    run_id: str = Field(..., description="LangSmith run identifier")
    score: float = Field(..., ge=0.0, le=1.0, description="Feedback score (0.0 to 1.0)")
    comment: Optional[str] = Field(None, description="Optional feedback comment")


class AgentFeedbackResponse(BaseModel):
    """Response schema for feedback submission.
    
    Attributes:
        success: Whether feedback was recorded successfully
        message: Status message
    """

    success: bool = Field(..., description="Whether feedback was recorded")
    message: str = Field(..., description="Status message")
