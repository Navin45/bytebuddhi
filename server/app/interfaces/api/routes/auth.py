"""Authentication API routes.

This module provides authentication endpoints including user registration,
login, token refresh, current user information retrieval, and password management.
"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status

from app.application.ports.output.repository.user_repository import UserRepository
from app.domain.models.user import User
from app.infrastructure.auth import jwt_handler, password_hasher
from app.infrastructure.config.logger import get_logger
from app.interfaces.api.dependencies import get_user_repository
from app.interfaces.api.middleware import get_current_user
from app.interfaces.api.schemas.auth_schema import (
    PasswordChangeRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Password reset token lifetime (15 minutes)
_PASSWORD_RESET_EXPIRE_MINUTES = 15


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: UserRegisterRequest,
    user_repo: UserRepository = Depends(get_user_repository),
):
    """Register a new user.
    
    Creates a new user account with the provided email and password.
    The password is securely hashed before storage.
    
    Args:
        request: User registration data
        user_repo: User repository instance
        
    Returns:
        UserResponse: Created user information
        
    Raises:
        HTTPException: If email is already registered
    """
    # Check if user already exists
    existing_user = await user_repo.get_by_email(request.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    # Hash password
    hashed_password = password_hasher.hash_password(request.password)
    
    # Generate username from email (before @ symbol)
    username = request.email.split('@')[0]
    
    # Create user
    user = User.create(
        email=request.email,
        username=username,
        password_hash=hashed_password,
    )
    
    created_user = await user_repo.create(user)
    
    logger.info("User registered", user_id=str(created_user.id), email=created_user.email)
    
    return UserResponse.model_validate(created_user)


@router.post("/login", response_model=TokenResponse)
async def login(
    request: UserLoginRequest,
    user_repo: UserRepository = Depends(get_user_repository),
):
    """Login user and return JWT tokens.
    
    Authenticates user with email and password, returning access
    and refresh tokens if credentials are valid.
    
    Args:
        request: Login credentials
        user_repo: User repository instance
        
    Returns:
        TokenResponse: Access and refresh tokens
        
    Raises:
        HTTPException: If credentials are invalid
    """
    # Get user by email
    user = await user_repo.get_by_email(request.email)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    # Verify password
    if not password_hasher.verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    
    # Generate tokens
    access_token = jwt_handler.create_access_token(user.id)
    refresh_token = jwt_handler.create_refresh_token(user.id)
    
    logger.info("User logged in", user_id=str(user.id), email=user.email)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=jwt_handler.access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    user_repo: UserRepository = Depends(get_user_repository),
):
    """Refresh access token using refresh token.
    
    Validates the refresh token and issues a new access token
    if the refresh token is valid.
    
    Args:
        request: Refresh token
        user_repo: User repository instance
        
    Returns:
        TokenResponse: New access and refresh tokens
        
    Raises:
        HTTPException: If refresh token is invalid
    """
    # Verify refresh token
    user_id = jwt_handler.verify_token(request.refresh_token, token_type="refresh")
    
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    
    # Get user
    user = await user_repo.get_by_id(user_id)
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    
    # Generate new tokens
    access_token = jwt_handler.create_access_token(user.id)
    new_refresh_token = jwt_handler.create_refresh_token(user.id)
    
    logger.info("Token refreshed", user_id=str(user.id))
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=jwt_handler.access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
):
    """Get current authenticated user information.
    
    Returns information about the currently authenticated user
    based on the JWT token in the request.
    
    Args:
        current_user: Current authenticated user from middleware
        
    Returns:
        UserResponse: Current user information
    """
    return UserResponse.model_validate(current_user)


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    request: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repository),
):
    """Change password for the currently authenticated user.
    
    Verifies the current password before updating to the new password.
    
    Args:
        request: Current and new password
        current_user: Authenticated user from JWT token
        user_repo: User repository instance
        
    Raises:
        HTTPException: If current password is incorrect
    """
    # Verify current password
    if not password_hasher.verify_password(request.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    
    # Ensure new password differs from current
    if request.current_password == request.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from current password",
        )
    
    # Hash new password and update user
    new_hash = password_hasher.hash_password(request.new_password)
    current_user.update_password(new_hash)
    await user_repo.update(current_user)
    
    logger.info("Password changed", user_id=str(current_user.id))


@router.post("/password/reset", response_model=dict)
async def request_password_reset(
    request: PasswordResetRequest,
    user_repo: UserRepository = Depends(get_user_repository),
):
    """Request a password reset token.
    
    Generates a short-lived reset token for the given email.
    Returns the token directly (in production this would be emailed).
    Always responds successfully to prevent user enumeration.
    
    Args:
        request: Email address for reset
        user_repo: User repository instance
        
    Returns:
        dict: Reset token (valid for 15 minutes)
    """
    user = await user_repo.get_by_email(request.email)
    
    if not user or not user.is_active:
        # Always return success to prevent user enumeration
        logger.info("Password reset requested for unknown/inactive email", email=request.email)
        return {"message": "If that email is registered, a reset token has been issued."}
    
    # Create a short-lived reset token using the existing JWT infrastructure
    reset_token = jwt_handler.create_access_token(
        user.id,
        additional_claims={
            "type": "password_reset",
            "exp": datetime.utcnow() + timedelta(minutes=_PASSWORD_RESET_EXPIRE_MINUTES),
        },
    )
    
    logger.info("Password reset token issued", user_id=str(user.id))
    
    # In production: send reset_token via email instead of returning it
    return {
        "message": "Password reset token issued.",
        "reset_token": reset_token,
        "expires_in_minutes": _PASSWORD_RESET_EXPIRE_MINUTES,
    }


@router.post("/password/reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(
    request: PasswordResetConfirm,
    user_repo: UserRepository = Depends(get_user_repository),
):
    """Confirm a password reset using the reset token.
    
    Validates the reset token and updates the user's password.
    
    Args:
        request: Reset token and new password
        user_repo: User repository instance
        
    Raises:
        HTTPException: If token is invalid/expired or user not found
    """
    # Verify and decode the reset token
    user_id = jwt_handler.verify_token(request.token, token_type="password_reset")
    
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    
    # Get the user
    user = await user_repo.get_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    
    # Hash new password and update
    new_hash = password_hasher.hash_password(request.new_password)
    user.update_password(new_hash)
    await user_repo.update(user)
    
    logger.info("Password reset confirmed", user_id=str(user.id))
