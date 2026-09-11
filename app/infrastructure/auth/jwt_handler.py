"""JWT token handling utilities.

This module provides JWT token generation and validation for
authentication. It supports both access tokens (short-lived) and
refresh tokens (long-lived).
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from jose import JWTError, jwt

from app.infrastructure.config.logger import get_logger
from app.infrastructure.config.settings import settings

logger = get_logger(__name__)

PROTECTED_TOKEN_CLAIMS = frozenset({"exp", "type", "sub", "iat", "nbf"})


class JWTHandler:
    """JWT token generation and validation.

    This class handles creating and validating JWT tokens for authentication.
    It supports both access tokens (for API access) and refresh tokens
    (for obtaining new access tokens).

    Attributes:
        secret_key: Secret key for signing tokens
        algorithm: JWT signing algorithm
        access_token_expire_minutes: Access token lifetime
        refresh_token_expire_days: Refresh token lifetime
    """

    def __init__(
        self,
        secret_key: str | None = None,
        algorithm: str | None = None,
        access_token_expire_minutes: int | None = None,
        refresh_token_expire_days: int | None = None,
    ):
        """Initialize JWT handler with configuration.

        Args:
            secret_key: Secret key for signing (defaults to settings)
            algorithm: Signing algorithm (defaults to settings)
            access_token_expire_minutes: Access token lifetime (defaults to settings)
            refresh_token_expire_days: Refresh token lifetime (defaults to settings)
        """
        self.secret_key = secret_key or settings.jwt_secret_key
        self.algorithm = algorithm or settings.jwt_algorithm
        self.access_token_expire_minutes = access_token_expire_minutes or settings.access_token_expire_minutes
        self.refresh_token_expire_days = refresh_token_expire_days or settings.refresh_token_expire_days

    def create_access_token(
        self,
        user_id: UUID,
        additional_claims: dict[str, Any] | None = None,
        *,
        token_type: str = "access",
        expires_delta: timedelta | None = None,
    ) -> str:
        """Create an access token for a user.

        Protected claims (exp, type, sub, iat, nbf) are owned by this constructor
        and cannot be overwritten by additional_claims.
        """
        expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=self.access_token_expire_minutes))
        extras = {k: v for k, v in (additional_claims or {}).items() if k not in PROTECTED_TOKEN_CLAIMS}
        to_encode: dict[str, Any] = {
            **extras,
            "sub": str(user_id),
            "exp": expire,
            "type": token_type,
            "iat": datetime.now(UTC),
        }
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return str(encoded_jwt)

    def create_refresh_token(self, user_id: UUID) -> str:
        """Create a refresh token for a user.

        Refresh tokens are long-lived and used to obtain new access tokens
        without requiring the user to log in again.

        Args:
            user_id: User ID to encode in token

        Returns:
            str: Encoded JWT refresh token
        """
        expire = datetime.now(UTC) + timedelta(days=self.refresh_token_expire_days)

        to_encode = {
            "sub": str(user_id),
            "exp": expire,
            "type": "refresh",
            "iat": datetime.now(UTC),
        }

        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return str(encoded_jwt)

    def verify_token(self, token: str, token_type: str = "access") -> UUID | None:
        """Verify and decode a JWT token.

        Validates the token signature, expiration, and type.
        Returns the user ID if valid, None otherwise.

        Args:
            token: JWT token to verify
            token_type: Expected token type (access or refresh)

        Returns:
            Optional[UUID]: User ID if token is valid, None otherwise
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])

            # Check token type
            if payload.get("type") != token_type:
                logger.warning("Invalid token type", expected=token_type, got=payload.get("type"))
                return None

            # Extract user ID
            user_id_str = payload.get("sub")
            if user_id_str is None:
                logger.warning("Token missing subject claim")
                return None

            return UUID(user_id_str)

        except JWTError as e:
            logger.warning("JWT verification failed", error=str(e))
            return None
        except ValueError as e:
            logger.warning("Invalid user ID in token", error=str(e))
            return None

    def decode_token(self, token: str) -> dict[str, Any] | None:
        """Decode a JWT token without verification.

        WARNING: This does not verify the token signature.
        Only use for debugging or when signature verification is not needed.

        Args:
            token: JWT token to decode

        Returns:
            Optional[Dict]: Token payload if decodable, None otherwise
        """
        try:
            payload = jwt.decode(
                token, self.secret_key, algorithms=[self.algorithm], options={"verify_signature": False}
            )
            return dict(payload)
        except JWTError as e:
            logger.error("Token decoding failed", error=str(e))
            return None


# Global JWT handler instance
jwt_handler = JWTHandler()
