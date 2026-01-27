"""Common Pydantic schemas used across API endpoints.

This module defines shared schemas for API responses, pagination,
and other common data structures.
"""

from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field


# Generic type variable for paginated responses
T = TypeVar("T")


class BaseResponse(BaseModel):
    """Base response model for all API responses.
    
    Provides a consistent structure for API responses with
    success status and optional message.
    """
    
    success: bool = Field(default=True, description="Whether the operation succeeded")
    message: Optional[str] = Field(default=None, description="Optional message")


class ErrorResponse(BaseModel):
    """Error response model for API errors.
    
    Used by the error handling middleware to return consistent
    error responses to clients.
    """
    
    success: bool = Field(default=False, description="Always false for errors")
    error: str = Field(..., description="Error type or code")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional error details")


class PaginationParams(BaseModel):
    """Query parameters for paginated endpoints.
    
    Provides standard pagination parameters that can be used
    across different list endpoints.
    """
    
    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")
    
    @property
    def offset(self) -> int:
        """Calculate database offset from page number.
        
        Returns:
            int: Offset for database query
        """
        return (self.page - 1) * self.page_size


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response model.
    
    Wraps a list of items with pagination metadata.
    Can be used for any type of paginated data.
    """
    
    items: List[T] = Field(..., description="List of items for current page")
    total: int = Field(..., description="Total number of items across all pages")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Number of items per page")
    total_pages: int = Field(..., description="Total number of pages")
    
    @classmethod
    def create(
        cls,
        items: List[T],
        total: int,
        page: int,
        page_size: int,
    ) -> "PaginatedResponse[T]":
        """Create a paginated response.
        
        Helper method to create a paginated response with calculated
        total_pages field.
        
        Args:
            items: List of items for current page
            total: Total number of items
            page: Current page number
            page_size: Items per page
            
        Returns:
            PaginatedResponse: Paginated response instance
        """
        total_pages = (total + page_size - 1) // page_size  # Ceiling division
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


class TimestampMixin(BaseModel):
    """Mixin for models with timestamp fields.
    
    Provides created_at and updated_at fields that are common
    across many entities.
    """
    
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class IDResponse(BaseModel):
    """Simple response containing just an ID.
    
    Useful for create operations that return the created entity's ID.
    """
    
    id: UUID = Field(..., description="Entity ID")


class HealthResponse(BaseModel):
    """Health check response model."""
    
    status: str = Field(..., description="Health status (healthy/unhealthy)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Check timestamp")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional health details")
