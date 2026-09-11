"""Base AST symbol and relation extractor."""

from typing import Any

from app.domain.models.code_intelligence import (
    CodeRelation,
    SourceLocation,
    Symbol,
    SyntaxDiagnostic,
)


class BaseLanguageExtractor:
    """Base class for language-specific AST symbol and relationship extraction."""

    def __init__(self, language_name: str) -> None:
        self.language_name = language_name

    def extract(
        self,
        root_node: Any,
        source_bytes: bytes,
        file_path: str,
        max_symbols: int = 500,
        max_relations: int = 1000,
    ) -> tuple[list[Symbol], list[CodeRelation], list[SyntaxDiagnostic]]:
        """Extract symbols, relationships, and diagnostics from parsed AST."""
        raise NotImplementedError

    @staticmethod
    def node_location(node: Any, file_path: str) -> SourceLocation:
        """Construct normalized 1-indexed line, 0-indexed column SourceLocation."""
        start_row, start_col = node.start_point[0], node.start_point[1]
        end_row, end_col = node.end_point[0], node.end_point[1]

        # Guard against malformed or negative bounds
        s_line = max(1, start_row + 1)
        s_col = max(0, start_col)
        e_line = max(s_line, end_row + 1)
        e_col = max(0, end_col)

        if s_line == e_line and e_col < s_col:
            e_col = s_col

        return SourceLocation(
            file_path=file_path,
            start_line=s_line,
            start_column=s_col,
            end_line=e_line,
            end_column=e_col,
        )

    @staticmethod
    def node_text(node: Any, source_bytes: bytes) -> str:
        """Decode slice of source bytes for a node."""
        return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace").strip()

    def find_syntax_diagnostics(
        self,
        root_node: Any,
        file_path: str,
        max_diagnostics: int = 50,
    ) -> list[SyntaxDiagnostic]:
        """Traverse tree to collect ERROR and MISSING nodes as syntax diagnostics."""
        diagnostics: list[SyntaxDiagnostic] = []
        stack = [root_node]
        while stack:
            curr = stack.pop()
            if curr.type == "ERROR" or curr.is_missing:
                desc = "missing token" if curr.is_missing else "syntax error"
                msg = f"Syntax diagnostic: {desc} near '{self.node_text(curr, b'')[:30]}'"
                diagnostics.append(
                    SyntaxDiagnostic(
                        message=msg,
                        location=self.node_location(curr, file_path),
                        severity="error",
                    )
                )
                if len(diagnostics) >= max_diagnostics:
                    break
            stack.extend(reversed(curr.children))
        return diagnostics
