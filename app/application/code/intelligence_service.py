"""CodeIntelligenceService coordinating safe discovery, parsing, indexing, and structural queries."""

import contextlib
import hashlib
import os
import time
from pathlib import Path
from typing import Any

from app.application.ports.output.code.code_index import CodeIndex
from app.application.ports.output.code.code_parser import CodeParser
from app.domain.exceptions.workspace_exceptions import (
    FileNotFoundWorkspaceError,
)
from app.domain.models.code_intelligence import (
    CodeRelation,
    CodeStructure,
    SourceLocation,
    Symbol,
    SymbolKind,
    SyntaxDiagnostic,
)
from app.domain.models.workspace import Workspace
from app.domain.value_objects.language import Language, ProgrammingLanguage
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class CodeIntelligenceService:
    """Coordinates workspace code discovery, Tree-sitter parsing, content-hash caching, and querying."""

    EXCLUDED_DIRS: set[str] = {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        "dist",
        "build",
        ".next",
        "target",
        ".idea",
        ".vscode",
        ".mypy_cache",
        ".ruff_cache",
        "storage",
    }

    def __init__(
        self,
        parser: CodeParser,
        index: CodeIndex,
        max_file_bytes: int = 1_000_000,  # 1 MB max per source file
        max_total_bytes: int = 10_000_000,  # 10 MB total per scan
        max_analysis_time: float = 30.0,  # 30 seconds max per batch analysis
    ) -> None:
        self.parser = parser
        self.index = index
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes
        self.max_analysis_time = max_analysis_time

    def detect_language(self, file_name_or_path: str) -> str:
        """Detect language canonically from file extension."""
        ext = Path(file_name_or_path).suffix.lower()
        lang_vo = Language.from_extension(ext)
        if lang_vo.value == ProgrammingLanguage.OTHER:
            # Special check for tsx/jsx if not in standard enum
            if ext == ".tsx":
                return "tsx"
            if ext == ".jsx":
                return "javascript"
            return "other"
        return lang_vo.name

    def get_canonical_relative_path(self, workspace: Workspace, path: str | Path) -> tuple[Path, str]:
        """Safely resolve path against workspace and return (resolved_Path, canonical_relative_str)."""
        resolved = workspace.resolve_path(path)
        rel_str = str(workspace.get_relative_path(resolved)).replace("\\", "/")
        return resolved, rel_str

    def discover_code_files(
        self,
        workspace: Workspace,
        subpath: str = ".",
        max_files: int = 200,
        include_unsupported: bool = False,
    ) -> list[str]:
        """Discover source files within workspace obeying boundaries and exclusion rules."""
        resolved_root, _ = self.get_canonical_relative_path(workspace, subpath)
        if not resolved_root.exists() or not resolved_root.is_dir():
            return []

        supported_langs = set(self.parser.supported_languages())
        code_files: list[str] = []

        for root, dirs, files in os.walk(resolved_root):
            # Prune excluded directories in-place
            dirs[:] = [d for d in dirs if d not in self.EXCLUDED_DIRS and not d.startswith(".")]

            for f in sorted(files):
                if f.startswith("."):
                    continue

                full_path = Path(root) / f
                if not workspace.is_safe_path(full_path):
                    continue

                lang = self.detect_language(f)
                if not include_unsupported and lang not in supported_langs:
                    continue

                rel_path = str(workspace.get_relative_path(full_path)).replace("\\", "/")
                code_files.append(rel_path)

                if len(code_files) >= max_files:
                    return code_files

        return code_files

    def analyze_file(
        self,
        workspace: Workspace,
        file_path: str | Path,
        force_reparse: bool = False,
    ) -> CodeStructure:
        """Analyze a single source file with content-hash cache invalidation."""
        resolved, canonical_path = self.get_canonical_relative_path(workspace, file_path)

        if not resolved.exists() or not resolved.is_file():
            raise FileNotFoundWorkspaceError(canonical_path)

        file_size = resolved.stat().st_size
        if file_size > self.max_file_bytes:
            diag = SyntaxDiagnostic(
                message=f"File exceeds maximum size limit ({file_size} > {self.max_file_bytes} bytes)",
                location=SourceLocation(
                    file_path=canonical_path, start_line=1, start_column=0, end_line=1, end_column=0
                ),
                severity="warning",
            )
            return CodeStructure(
                file_path=canonical_path,
                language=self.detect_language(canonical_path),
                content_hash="",
                diagnostics=[diag],
            )

        try:
            content_bytes = resolved.read_bytes()
        except Exception as e:
            logger.error("Failed to read file for code analysis", path=canonical_path, error=str(e))
            raise

        content_hash = hashlib.sha256(content_bytes).hexdigest()
        lang = self.detect_language(canonical_path)

        # Content-hash incremental cache check
        if not force_reparse:
            cached_hash = self.index.get_content_hash(canonical_path)
            if cached_hash == content_hash:
                cached_struct = self.index.get(canonical_path)
                if cached_struct and cached_struct.language == lang:
                    return cached_struct

        # Parse with Tree-sitter
        structure = self.parser.parse(content_bytes, language=lang, file_path=canonical_path)

        # Update index
        self.index.set(canonical_path, structure)
        return structure

    def analyze_workspace(
        self,
        workspace: Workspace,
        subpath: str = ".",
        max_files: int = 100,
    ) -> dict[str, CodeStructure]:
        """Analyze all discovered code files within workspace up to bounded limits."""
        files = self.discover_code_files(workspace, subpath=subpath, max_files=max_files)
        total_bytes = 0
        start_time = time.monotonic()
        results: dict[str, CodeStructure] = {}

        for f in files:
            elapsed = time.monotonic() - start_time
            if elapsed > self.max_analysis_time:
                logger.warning(
                    "Reached maximum analysis time limit for workspace analysis",
                    elapsed=elapsed,
                    max_analysis_time=self.max_analysis_time,
                )
                break

            resolved, _ = self.get_canonical_relative_path(workspace, f)
            size = resolved.stat().st_size
            if total_bytes + size > self.max_total_bytes:
                logger.warning("Reached maximum total byte limit for workspace analysis", total_bytes=total_bytes)
                break
            total_bytes += size
            try:
                results[f] = self.analyze_file(workspace, f)
            except Exception as e:
                logger.warning("Failed analyzing file in batch, skipping", file=f, error=str(e))

        return results

    def invalidate_file(self, workspace: Workspace, file_path: str | Path) -> bool:
        """Invalidate and remove cached analysis for a file (e.g. on deletion)."""
        _, canonical_path = self.get_canonical_relative_path(workspace, file_path)
        return self.index.remove(canonical_path)

    def find_symbol(
        self,
        workspace: Workspace,
        name: str,
        file_path: str | Path | None = None,
    ) -> Symbol | None:
        """Find the primary symbol definition matching exact name or qualified name."""
        canonical_path = None
        if file_path:
            _, canonical_path = self.get_canonical_relative_path(workspace, file_path)
            if not self.index.get(canonical_path):
                with contextlib.suppress(Exception):
                    self.analyze_file(workspace, canonical_path)

        symbols = self.index.find_symbols(query=name, file_path=canonical_path, limit=10)
        # Prioritize exact match
        for s in symbols:
            if s.name == name or s.qualified_name == name:
                return s
        return symbols[0] if symbols else None

    def find_symbols(
        self,
        workspace: Workspace,
        query: str = "",
        kind: SymbolKind | None = None,
        file_path: str | Path | None = None,
        limit: int = 20,
    ) -> list[Symbol]:
        """Search symbols across indexed files, bounding results."""
        limit_bounded = max(1, min(limit, 50))
        canonical_path = None
        if file_path:
            _, canonical_path = self.get_canonical_relative_path(workspace, file_path)
            if not self.index.get(canonical_path):
                with contextlib.suppress(Exception):
                    self.analyze_file(workspace, canonical_path)

        return self.index.find_symbols(
            query=query,
            kind=kind,
            file_path=canonical_path,
            limit=limit_bounded,
        )

    def find_references(
        self,
        workspace: Workspace,
        symbol_name: str,
        limit: int = 20,
    ) -> list[CodeRelation]:
        """Find syntactic references, calls, imports, and inheritance relations mentioning symbol."""
        limit_bounded = max(1, min(limit, 50))
        matching: list[CodeRelation] = []

        target_name_lower = symbol_name.lower().strip()

        for structure in self.index.get_all_structures():
            for rel in structure.relationships:
                # Match target or source
                if (
                    rel.target_name.lower() == target_name_lower
                    or rel.target_name.lower().endswith(f".{target_name_lower}")
                    or rel.target_name.lower().endswith(f"::{target_name_lower}")
                ):
                    matching.append(rel)
                    if len(matching) >= limit_bounded:
                        return matching

        return matching

    def get_code_structure(
        self,
        workspace: Workspace,
        file_path: str | Path,
        max_depth: int = 3,
    ) -> dict[str, Any]:
        """Return structural hierarchy of symbols and relationships for a file without raw content."""
        structure = self.analyze_file(workspace, file_path)

        # Build clean hierarchical view derived on-demand from canonical flat list
        top_level_symbols = [s for s in structure.symbols if not s.parent_name]
        children_by_parent: dict[str, list[Symbol]] = {}
        for s in structure.symbols:
            if s.parent_name:
                children_by_parent.setdefault(s.parent_name, []).append(s)

        def build_sym_tree(sym: Symbol, current_depth: int) -> dict[str, Any]:
            node: dict[str, Any] = {
                "name": sym.name,
                "qualified_name": sym.qualified_name,
                "kind": sym.kind.value,
                "line": sym.location.start_line,
                "signature": sym.signature,
            }
            if sym.docstring:
                node["docstring"] = sym.docstring[:120]

            if current_depth < max_depth:
                kids = children_by_parent.get(sym.qualified_name, [])
                if kids:
                    node["children"] = [build_sym_tree(k, current_depth + 1) for k in kids]
            return node

        return {
            "file_path": structure.file_path,
            "language": structure.language,
            "total_lines": structure.total_lines,
            "symbols": [build_sym_tree(s, 1) for s in top_level_symbols],
            "imports": [r.to_dict() for r in structure.relationships if r.relation_type.value == "imports"],
            "diagnostics_count": len(structure.diagnostics),
        }

    def search_code_structure(
        self,
        workspace: Workspace,
        query: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search structural metadata (names, signatures, docstrings) across indexed files."""
        limit_bounded = max(1, min(limit, 50))
        q_lower = query.lower().strip()
        matches: list[dict[str, Any]] = []

        for structure in self.index.get_all_structures():
            for sym in structure.symbols:
                name_match = q_lower in sym.name.lower()
                sig_match = q_lower in (sym.signature or "").lower()
                doc_match = q_lower in (sym.docstring or "").lower()

                if name_match or sig_match or doc_match:
                    matches.append(
                        {
                            "file_path": sym.location.file_path,
                            "symbol": sym.name,
                            "qualified_name": sym.qualified_name,
                            "kind": sym.kind.value,
                            "line": sym.location.start_line,
                            "signature": sym.signature,
                            "docstring": sym.docstring[:100] if sym.docstring else None,
                        }
                    )
                    if len(matches) >= limit_bounded:
                        return matches

        return matches
