"""Language value object.

This module provides a value object for programming languages.
Ensures only supported languages are used.
"""

from enum import Enum
from typing import Any


class ProgrammingLanguage(str, Enum):
    """Supported programming languages.
    
    This enum defines all programming languages supported by ByteBuddhi
    for code analysis and generation.
    """

    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JAVA = "java"
    GO = "go"
    RUST = "rust"
    CPP = "cpp"
    C = "c"
    CSHARP = "csharp"
    PHP = "php"
    RUBY = "ruby"
    SWIFT = "swift"
    KOTLIN = "kotlin"
    SCALA = "scala"
    OTHER = "other"


class Language:
    """Programming language value object.
    
    This class represents a programming language as a value object,
    ensuring only valid languages are used.
    
    Attributes:
        value: The programming language
    """

    # File extension to language mapping
    EXTENSION_MAP = {
        ".py": ProgrammingLanguage.PYTHON,
        ".js": ProgrammingLanguage.JAVASCRIPT,
        ".jsx": ProgrammingLanguage.JAVASCRIPT,
        ".ts": ProgrammingLanguage.TYPESCRIPT,
        ".tsx": ProgrammingLanguage.TYPESCRIPT,
        ".java": ProgrammingLanguage.JAVA,
        ".go": ProgrammingLanguage.GO,
        ".rs": ProgrammingLanguage.RUST,
        ".cpp": ProgrammingLanguage.CPP,
        ".cc": ProgrammingLanguage.CPP,
        ".cxx": ProgrammingLanguage.CPP,
        ".c": ProgrammingLanguage.C,
        ".h": ProgrammingLanguage.C,
        ".cs": ProgrammingLanguage.CSHARP,
        ".php": ProgrammingLanguage.PHP,
        ".rb": ProgrammingLanguage.RUBY,
        ".swift": ProgrammingLanguage.SWIFT,
        ".kt": ProgrammingLanguage.KOTLIN,
        ".scala": ProgrammingLanguage.SCALA,
    }

    def __init__(self, value: str):
        """Initialize language with validation.
        
        Args:
            value: Language name (case-insensitive)
            
        Raises:
            ValueError: If language is not supported
        """
        if not value:
            raise ValueError("Language cannot be empty")
        
        # Normalize to lowercase
        normalized = value.lower().strip()
        
        # Try to match to enum
        try:
            self._value = ProgrammingLanguage(normalized)
        except ValueError:
            # Default to OTHER for unknown languages
            self._value = ProgrammingLanguage.OTHER

    @classmethod
    def from_extension(cls, extension: str) -> "Language":
        """Create Language from file extension.
        
        Args:
            extension: File extension (e.g., '.py')
            
        Returns:
            Language: Language instance
        """
        lang = cls.EXTENSION_MAP.get(extension.lower(), ProgrammingLanguage.OTHER)
        return cls(lang.value)

    @property
    def value(self) -> ProgrammingLanguage:
        """Get the language value.
        
        Returns:
            ProgrammingLanguage: The language enum
        """
        return self._value

    @property
    def name(self) -> str:
        """Get language name.
        
        Returns:
            str: Language name
        """
        return self._value.value

    def __str__(self) -> str:
        """String representation of language.
        
        Returns:
            str: Language name
        """
        return self._value.value

    def __repr__(self) -> str:
        """Developer-friendly representation.
        
        Returns:
            str: Language representation
        """
        return f"Language('{self._value.value}')"

    def __eq__(self, other: Any) -> bool:
        """Check equality with another language.
        
        Args:
            other: Object to compare with
            
        Returns:
            bool: True if languages are equal
        """
        if not isinstance(other, Language):
            return False
        return self._value == other._value

    def __hash__(self) -> int:
        """Hash for use in sets and dicts.
        
        Returns:
            int: Hash value
        """
        return hash(self._value)
