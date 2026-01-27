"""Password hashing utilities.

This module provides secure password hashing and verification
using bcrypt. All passwords are hashed before storage and never
stored in plain text.
"""

from passlib.context import CryptContext

from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class PasswordHasher:
    """Password hashing and verification using bcrypt.
    
    This class provides methods to securely hash passwords and verify
    them against stored hashes. It uses bcrypt with automatic salt generation.
    
    Attributes:
        pwd_context: Passlib CryptContext configured for bcrypt
    """

    def __init__(self):
        """Initialize password hasher with bcrypt configuration."""
        self.pwd_context = CryptContext(
            schemes=["bcrypt"],
            deprecated="auto",
            bcrypt__rounds=12,  # Cost factor for bcrypt
        )

    def hash_password(self, password: str) -> str:
        """Hash a plain text password.
        
        Generates a secure hash of the password using bcrypt with
        automatic salt generation. The hash includes the salt and
        can be stored directly in the database.
        
        Args:
            password: Plain text password to hash
            
        Returns:
            str: Hashed password (includes salt)
        """
        return self.pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against a hash.
        
        Compares a plain text password with a stored hash to verify
        if they match. This is a constant-time operation to prevent
        timing attacks.
        
        Args:
            plain_password: Plain text password to verify
            hashed_password: Stored password hash
            
        Returns:
            bool: True if password matches hash, False otherwise
        """
        try:
            return self.pwd_context.verify(plain_password, hashed_password)
        except Exception as e:
            logger.error("Password verification failed", error=str(e))
            return False

    def needs_rehash(self, hashed_password: str) -> bool:
        """Check if a password hash needs to be updated.
        
        Determines if a hash was created with deprecated parameters
        and should be rehashed with current settings.
        
        Args:
            hashed_password: Stored password hash
            
        Returns:
            bool: True if hash should be updated, False otherwise
        """
        return self.pwd_context.needs_update(hashed_password)


# Global password hasher instance
password_hasher = PasswordHasher()
