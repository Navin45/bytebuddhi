"""In-memory implementation of CodeIndex with content-hash tracking."""

from app.domain.models.code_intelligence import CodeStructure, Symbol, SymbolKind


class InMemoryCodeIndex:
    """Thread-safe and fast in-memory code index storing CodeStructure instances by canonical path."""

    def __init__(self) -> None:
        self._entries: dict[str, CodeStructure] = {}

    def set(self, file_path: str, structure: CodeStructure) -> None:
        """Store or replace the parsed structure for the canonical file path."""
        self._entries[file_path] = structure

    def get(self, file_path: str) -> CodeStructure | None:
        """Retrieve the parsed structure for the file path if present."""
        return self._entries.get(file_path)

    def get_content_hash(self, file_path: str) -> str | None:
        """Retrieve the cached content hash for the file path."""
        entry = self._entries.get(file_path)
        return entry.content_hash if entry else None

    def remove(self, file_path: str) -> bool:
        """Remove all indexed information for a file path. Returns True if existed."""
        return self._entries.pop(file_path, None) is not None

    def clear(self) -> None:
        """Purge all indexed structures."""
        self._entries.clear()

    def find_symbols(
        self,
        query: str = "",
        kind: SymbolKind | None = None,
        file_path: str | None = None,
        limit: int = 20,
    ) -> list[Symbol]:
        """Search indexed symbols matching query, kind, and/or file_path."""
        query_norm = query.strip().lower()
        results: list[Symbol] = []

        target_structures: list[CodeStructure]
        if file_path:
            st = self._entries.get(file_path)
            target_structures = [st] if st else []
        else:
            target_structures = list(self._entries.values())

        for structure in target_structures:
            for sym in structure.symbols:
                if kind is not None and sym.kind != kind:
                    continue

                if query_norm:
                    name_match = query_norm in sym.name.lower()
                    qual_match = query_norm in sym.qualified_name.lower()
                    if not (name_match or qual_match):
                        continue

                results.append(sym)
                if len(results) >= limit:
                    return results

        return results

    def get_all_structures(self) -> list[CodeStructure]:
        """Return all indexed structures."""
        return list(self._entries.values())
