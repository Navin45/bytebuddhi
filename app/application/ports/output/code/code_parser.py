"""CodeParser port protocol."""

from typing import Protocol, runtime_checkable

from app.domain.models.code_intelligence import CodeStructure


@runtime_checkable
class CodeParser(Protocol):
    """Abstract port for parsing source code into a normalized CodeStructure."""

    def parse(self, content: str | bytes, language: str, file_path: str = "") -> CodeStructure:
        """Parse source content into a normalized CodeStructure.

        Must be resilient: syntax errors must not raise unhandled exceptions;
        they should be recorded as SyntaxDiagnostic objects while extracting
        all valid syntax symbols.
        """
        ...

    def can_parse(self, language: str) -> bool:
        """Return whether the parser supports the requested language."""
        ...

    def supported_languages(self) -> list[str]:
        """Return list of supported canonical language identifiers."""
        ...
