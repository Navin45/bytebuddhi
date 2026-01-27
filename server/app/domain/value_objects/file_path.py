"""File path value object.

This module provides a value object for file paths with validation.
Ensures file paths are valid and normalized.
"""

from pathlib import Path
from typing import Any


class FilePath:
    """File path value object with validation.
    
    This class represents a file path as a value object, ensuring
    paths are valid and normalized. Immutable once created.
    
    Attributes:
        value: The normalized file path string
    """

    def __init__(self, value: str):
        """Initialize file path with validation.
        
        Args:
            value: File path string
            
        Raises:
            ValueError: If path is empty or invalid
        """
        if not value:
            raise ValueError("File path cannot be empty")
        
        # Normalize path
        try:
            path = Path(value).resolve()
            self._value = str(path)
            self._path = path
        except Exception as e:
            raise ValueError(f"Invalid file path: {value}") from e

    @property
    def value(self) -> str:
        """Get the file path value.
        
        Returns:
            str: The normalized file path
        """
        return self._value

    @property
    def path(self) -> Path:
        """Get Path object.
        
        Returns:
            Path: pathlib.Path object
        """
        return self._path

    def __str__(self) -> str:
        """String representation of file path.
        
        Returns:
            str: The file path
        """
        return self._value

    def __repr__(self) -> str:
        """Developer-friendly representation.
        
        Returns:
            str: FilePath representation
        """
        return f"FilePath('{self._value}')"

    def __eq__(self, other: Any) -> bool:
        """Check equality with another file path.
        
        Args:
            other: Object to compare with
            
        Returns:
            bool: True if paths are equal
        """
        if not isinstance(other, FilePath):
            return False
        return self._value == other._value

    def __hash__(self) -> int:
        """Hash for use in sets and dicts.
        
        Returns:
            int: Hash value
        """
        return hash(self._value)

    @property
    def name(self) -> str:
        """Get file name.
        
        Returns:
            str: File name with extension
        """
        return self._path.name

    @property
    def extension(self) -> str:
        """Get file extension.
        
        Returns:
            str: File extension (e.g., '.py')
        """
        return self._path.suffix

    @property
    def parent(self) -> str:
        """Get parent directory.
        
        Returns:
            str: Parent directory path
        """
        return str(self._path.parent)

    def exists(self) -> bool:
        """Check if file exists.
        
        Returns:
            bool: True if file exists
        """
        return self._path.exists()

    def is_file(self) -> bool:
        """Check if path is a file.
        
        Returns:
            bool: True if path is a file
        """
        return self._path.is_file()

    def is_directory(self) -> bool:
        """Check if path is a directory.
        
        Returns:
            bool: True if path is a directory
        """
        return self._path.is_dir()
