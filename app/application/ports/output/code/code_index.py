"""CodeIndex port protocol."""

from typing import Protocol, runtime_checkable

from app.domain.models.code_intelligence import CodeStructure, Symbol, SymbolKind


@runtime_checkable
class CodeIndex(Protocol):
    """Abstract port for storing and querying parsed code structures and symbols."""

    def set(self, file_path: str, structure: CodeStructure) -> None:
        """Store or update the parsed structure for a canonical file path."""
        ...

    def get(self, file_path: str) -> CodeStructure | None:
        """Retrieve the parsed structure for a canonical file path if present."""
        ...

    def get_content_hash(self, file_path: str) -> str | None:
        """Retrieve the cached content hash for a file path if indexed."""
        ...

    def remove(self, file_path: str) -> bool:
        """Remove all indexed symbols and structure for a file path."""
        ...

    def clear(self) -> None:
        """Clear all entries from the index."""
        ...

    def find_symbols(
        self,
        query: str = "",
        kind: SymbolKind | None = None,
        file_path: str | None = None,
        limit: int = 20,
    ) -> list[Symbol]:
        """Search indexed symbols across files by query, kind, or path."""
        ...

    def get_all_structures(self) -> list[CodeStructure]:
        """Return all indexed CodeStructure instances."""
        ...
