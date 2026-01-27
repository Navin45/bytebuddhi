"""Authentication middleware for FastAPI.

This module provides middleware to authenticate requests using JWT tokens.
It extracts the token from the Authorization header, validates it, and
makes the authenticated user available to route handlers.
"""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.ports.output.repository.user_repository import UserRepository
from app.domain.models.user import User
from app.infrastructure.auth.jwt_handler import jwt_handler
from app.infrastructure.config.logger import get_logger
from app.interfaces.api.dependencies import get_user_repository

logger = get_logger(__name__)

# HTTP Bearer token scheme
security = HTTPBearer()


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> UUID:
    """Extract and validate user ID from JWT token.
    
    This dependency extracts the JWT token from the Authorization header,
    validates it, and returns the user ID. Raises HTTPException if token
    is invalid or missing.
    
    Args:
        credentials: HTTP bearer credentials from request
        
    Returns:
        UUID: Authenticated user ID
        
    Raises:
        HTTPException: If token is invalid or missing
    """
    token = credentials.credentials
    
    user_id = jwt_handler.verify_token(token, token_type="access")
    
    if user_id is None:
        logger.warning("Invalid or expired access token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user_id


async def get_current_user(
    user_id: UUID = Depends(get_current_user_id),
    user_repo: UserRepository = Depends(get_user_repository),
) -> User:
    """Get the current authenticated user.
    
    This dependency retrieves the full user object from the database
    using the user ID from the JWT token. Raises HTTPException if user
    is not found or inactive.
    
    Args:
        user_id: User ID from JWT token
        user_repo: User repository instance
        
    Returns:
        User: Authenticated user object
        
    Raises:
        HTTPException: If user not found or inactive
    """
    user = await user_repo.get_by_id(user_id)
    
    if user is None:
        logger.warning("User not found", user_id=str(user_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    if not user.is_active:
        logger.warning("Inactive user attempted access", user_id=str(user_id))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    
    return user


async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    user_repo: UserRepository = Depends(get_user_repository),
) -> Optional[User]:
    """Get the current user if authenticated, None otherwise.
    
    This dependency is for endpoints that support optional authentication.
    It returns the user if a valid token is provided, or None if no token
    or an invalid token is provided.
    
    Args:
        credentials: Optional HTTP bearer credentials
        user_repo: User repository instance
        
    Returns:
        Optional[User]: Authenticated user or None
    """
    if credentials is None:
        return None
    
    token = credentials.credentials
    user_id = jwt_handler.verify_token(token, token_type="access")
    
    if user_id is None:
        return None
    
    user = await user_repo.get_by_id(user_id)
    
    if user is None or not user.is_active:
        return None
    
    return user
