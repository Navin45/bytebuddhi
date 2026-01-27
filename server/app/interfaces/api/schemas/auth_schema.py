"""Authentication schemas for API requests and responses.

This module defines Pydantic schemas for authentication-related
endpoints including registration, login, and token management.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.interfaces.api.schemas.common import TimestampMixin


class UserRegisterRequest(BaseModel):
    """Request schema for user registration."""
    
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, max_length=100, description="User password (min 8 characters)")
    full_name: Optional[str] = Field(default=None, max_length=200, description="User full name")


class UserLoginRequest(BaseModel):
    """Request schema for user login."""
    
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")


class TokenResponse(BaseModel):
    """Response schema for authentication tokens."""
    
    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Access token expiration time in seconds")


class RefreshTokenRequest(BaseModel):
    """Request schema for refreshing access token."""
    
    refresh_token: str = Field(..., description="Refresh token")


class UserResponse(TimestampMixin):
    """Response schema for user information."""
    
    id: UUID = Field(..., description="User ID")
    email: EmailStr = Field(..., description="User email")
    full_name: Optional[str] = Field(default=None, description="User full name")
    is_active: bool = Field(..., description="Whether user account is active")
    quota_used: int = Field(..., description="API quota used this month")
    quota_limit: int = Field(..., description="Monthly API quota limit")
    
    class Config:
        """Pydantic configuration."""
        from_attributes = True


class PasswordChangeRequest(BaseModel):
    """Request schema for changing password."""
    
    current_password: str = Field(..., description="Current password")
    new_password: str = Field(..., min_length=8, max_length=100, description="New password (min 8 characters)")


class PasswordResetRequest(BaseModel):
    """Request schema for initiating password reset."""
    
    email: EmailStr = Field(..., description="User email address")


class PasswordResetConfirm(BaseModel):
    """Request schema for confirming password reset."""
    
    token: str = Field(..., description="Password reset token")
    new_password: str = Field(..., min_length=8, max_length=100, description="New password (min 8 characters)")
