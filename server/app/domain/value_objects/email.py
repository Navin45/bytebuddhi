"""Email value object.

This module provides a value object for email addresses with validation.
Value objects are immutable and ensure domain invariants are maintained.
"""

import re
from typing import Any


class Email:
    """Email value object with validation.
    
    This class represents an email address as a value object, ensuring
    that only valid email addresses can be created. Once created, the
    email is immutable.
    
    Attributes:
        value: The validated email address string
    """

    # Simple email validation pattern
    EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

    def __init__(self, value: str):
        """Initialize email with validation.
        
        Args:
            value: Email address string
            
        Raises:
            ValueError: If email format is invalid
        """
        if not value:
            raise ValueError("Email cannot be empty")
        
        # Normalize email to lowercase
        normalized = value.strip().lower()
        
        if not self.EMAIL_PATTERN.match(normalized):
            raise ValueError(f"Invalid email format: {value}")
        
        self._value = normalized

    @property
    def value(self) -> str:
        """Get the email address value.
        
        Returns:
            str: The email address
        """
        return self._value

    def __str__(self) -> str:
        """String representation of email.
        
        Returns:
            str: The email address
        """
        return self._value

    def __repr__(self) -> str:
        """Developer-friendly representation.
        
        Returns:
            str: Email representation
        """
        return f"Email('{self._value}')"

    def __eq__(self, other: Any) -> bool:
        """Check equality with another email.
        
        Args:
            other: Object to compare with
            
        Returns:
            bool: True if emails are equal
        """
        if not isinstance(other, Email):
            return False
        return self._value == other._value

    def __hash__(self) -> int:
        """Hash for use in sets and dicts.
        
        Returns:
            int: Hash value
        """
        return hash(self._value)

    @property
    def domain(self) -> str:
        """Extract domain from email.
        
        Returns:
            str: Email domain (e.g., 'example.com')
        """
        return self._value.split("@")[1]

    @property
    def local_part(self) -> str:
        """Extract local part from email.
        
        Returns:
            str: Email local part (before @)
        """
        return self._value.split("@")[0]
