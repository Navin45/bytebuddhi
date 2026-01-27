"""Authentication API routes.

This module provides authentication endpoints including user registration,
login, token refresh, and current user information retrieval.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.ports.output.repository.user_repository import UserRepository
from app.domain.models.user import User
from app.infrastructure.auth import jwt_handler, password_hasher
from app.infrastructure.config.logger import get_logger
from app.interfaces.api.dependencies import get_user_repository
from app.interfaces.api.middleware import get_current_user
from app.interfaces.api.schemas.auth_schema import (
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
    RefreshTokenRequest,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


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
    
    # Create user
    user = User.create(
        email=request.email,
        hashed_password=hashed_password,
        full_name=request.full_name,
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
    if not password_hasher.verify_password(request.password, user.hashed_password):
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
