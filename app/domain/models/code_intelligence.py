"""Domain models for code intelligence independent of parser implementation details."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class SourceLocation:
    """Represents a code coordinate span within a source file.

    Invariant:
        start_line and end_line are 1-indexed (>= 1).
        start_column and end_column are 0-indexed (>= 0).
    """

    file_path: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int

    def __post_init__(self) -> None:
        if self.start_line < 1 or self.end_line < 1:
            raise ValueError(f"Line numbers must be 1-indexed (got start={self.start_line}, end={self.end_line})")
        if self.start_column < 0 or self.end_column < 0:
            raise ValueError(f"Columns must be 0-indexed (got start={self.start_column}, end={self.end_column})")
        if self.start_line > self.end_line or (
            self.start_line == self.end_line and self.start_column > self.end_column
        ):
            raise ValueError(
                f"Start coordinate ({self.start_line}:{self.start_column}) "
                f"cannot exceed end coordinate ({self.end_line}:{self.end_column})"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "start_line": self.start_line,
            "start_column": self.start_column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }


class SymbolKind(StrEnum):
    """Categorization of code symbols."""

    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    CONSTANT = "constant"
    INTERFACE = "interface"
    TYPE_ALIAS = "type_alias"
    IMPORT = "import"


@dataclass
class Symbol:
    """A normalized code symbol representation.

    Hierarchy is preserved canonically via parent_name and qualified_name
    to avoid duplicating symbol instances into nested collections.
    """

    id: str
    name: str
    qualified_name: str
    kind: SymbolKind
    location: SourceLocation
    language: str
    signature: str | None = None
    docstring: str | None = None
    parent_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "kind": self.kind.value,
            "location": self.location.to_dict(),
            "language": self.language,
            "signature": self.signature,
            "docstring": self.docstring,
            "parent_name": self.parent_name,
            "metadata": self.metadata,
        }


class CodeRelationType(StrEnum):
    """Normalized relationships between code entities."""

    DEFINES = "defines"
    CONTAINS = "contains"
    IMPORTS = "imports"
    CALLS = "calls"
    REFERENCES = "references"
    INHERITS = "inherits"


@dataclass(frozen=True)
class CodeRelation:
    """A directional structural relationship between code identifiers.

    is_syntactic distinguishes purely syntax-derived links (e.g. AST call node)
    from compiler-grade semantic resolution.
    """

    source_name: str
    target_name: str
    relation_type: CodeRelationType
    location: SourceLocation | None = None
    is_syntactic: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "target_name": self.target_name,
            "relation_type": self.relation_type.value,
            "location": self.location.to_dict() if self.location else None,
            "is_syntactic": self.is_syntactic,
        }


@dataclass(frozen=True)
class SyntaxDiagnostic:
    """A syntax diagnostic emitted during source code analysis."""

    message: str
    location: SourceLocation
    severity: str = "error"  # "error" | "warning"

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "location": self.location.to_dict(),
            "severity": self.severity,
        }


@dataclass
class CodeStructure:
    """Complete parsed structural representation of a source file."""

    file_path: str
    language: str
    content_hash: str
    symbols: list[Symbol] = field(default_factory=list)
    relationships: list[CodeRelation] = field(default_factory=list)
    diagnostics: list[SyntaxDiagnostic] = field(default_factory=list)
    total_lines: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "language": self.language,
            "content_hash": self.content_hash,
            "symbols": [s.to_dict() for s in self.symbols],
            "relationships": [r.to_dict() for r in self.relationships],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "total_lines": self.total_lines,
        }
