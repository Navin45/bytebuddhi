"""Password hashing utilities.

This module provides secure password hashing and verification
using bcrypt. All passwords are hashed before storage and never
stored in plain text.
"""

import bcrypt

from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class PasswordHasher:
    """Password hashing and verification using bcrypt.
    
    This class provides methods to securely hash passwords and verify
    them against stored hashes. It uses bcrypt with automatic salt generation.
    
    Attributes:
        rounds: Cost factor for bcrypt (default: 12)
    """

    def __init__(self, rounds: int = 12):
        """Initialize password hasher with bcrypt configuration.
        
        Args:
            rounds: Cost factor for bcrypt (default: 12). Higher values are more secure
                   but slower. Each increment doubles the computation time.
        """
        self.rounds = rounds

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
        # Convert password to bytes
        password_bytes = password.encode('utf-8')
        
        # Generate salt and hash
        salt = bcrypt.gensalt(rounds=self.rounds)
        hashed = bcrypt.hashpw(password_bytes, salt)
        
        # Return as string
        return hashed.decode('utf-8')

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
            # Convert to bytes
            password_bytes = plain_password.encode('utf-8')
            hashed_bytes = hashed_password.encode('utf-8')
            
            # Verify using bcrypt
            return bcrypt.checkpw(password_bytes, hashed_bytes)
        except Exception as e:
            logger.error("Password verification failed", error=str(e))
            return False

    def needs_rehash(self, hashed_password: str) -> bool:
        """Check if a password hash needs to be updated.
        
        Determines if a hash was created with different cost factor
        and should be rehashed with current settings.
        
        Args:
            hashed_password: Stored password hash
            
        Returns:
            bool: True if hash should be updated, False otherwise
        """
        try:
            # Extract the cost factor from the hash
            # bcrypt hashes have format: $2b$<cost>$<salt+hash>
            hashed_bytes = hashed_password.encode('utf-8')
            parts = hashed_bytes.split(b'$')
            
            if len(parts) >= 3:
                current_rounds = int(parts[2])
                return current_rounds != self.rounds
            
            return False
        except Exception as e:
            logger.error("Failed to check if rehash needed", error=str(e))
            return False


# Global password hasher instance
password_hasher = PasswordHasher()
