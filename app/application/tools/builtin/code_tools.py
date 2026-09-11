"""Builtin code intelligence tools powered by CodeIntelligenceService."""

import contextlib
from typing import Any

from app.application.code.intelligence_service import CodeIntelligenceService
from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import ToolDefinition
from app.domain.models.code_intelligence import SymbolKind
from app.domain.models.workspace import Workspace


def create_code_tools(
    code_service: CodeIntelligenceService,
    default_workspace: Workspace | None = None,
) -> list[tuple[ToolDefinition, Any]]:
    """Create and return tool definitions and handlers for code intelligence operations."""

    def _get_workspace(context: ToolExecutionContext | None) -> Workspace:
        ws = context.workspace if context else default_workspace
        if not ws:
            raise ValueError("No workspace available for code intelligence tool execution")
        return ws

    async def list_code_files_handler(
        subpath: str = ".",
        max_files: int = 50,
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        ws = _get_workspace(context)
        bounded_limit = max(1, min(max_files, 200))
        files = code_service.discover_code_files(ws, subpath=subpath, max_files=bounded_limit)
        return {
            "subpath": subpath,
            "files": files,
            "count": len(files),
            "max_files_limit": bounded_limit,
        }

    async def get_code_structure_handler(
        path: str,
        max_depth: int = 3,
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        ws = _get_workspace(context)
        bounded_depth = max(1, min(max_depth, 5))
        return code_service.get_code_structure(ws, file_path=path, max_depth=bounded_depth)

    async def get_symbol_definition_handler(
        name: str,
        file_path: str | None = None,
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        ws = _get_workspace(context)
        sym = code_service.find_symbol(ws, name=name, file_path=file_path)
        if not sym:
            return {"found": False, "name": name, "message": f"Symbol '{name}' not found"}
        return {"found": True, "symbol": sym.to_dict()}

    async def find_symbols_handler(
        query: str = "",
        kind: str | None = None,
        file_path: str | None = None,
        limit: int = 20,
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        ws = _get_workspace(context)
        bounded_limit = max(1, min(limit, 50))
        sym_kind = None
        if kind:
            with contextlib.suppress(ValueError):
                sym_kind = SymbolKind(kind.lower().strip())
        symbols = code_service.find_symbols(
            ws,
            query=query,
            kind=sym_kind,
            file_path=file_path,
            limit=bounded_limit,
        )
        return {
            "query": query,
            "count": len(symbols),
            "symbols": [s.to_dict() for s in symbols],
        }

    async def find_references_handler(
        symbol_name: str,
        limit: int = 20,
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        ws = _get_workspace(context)
        bounded_limit = max(1, min(limit, 50))
        refs = code_service.find_references(ws, symbol_name=symbol_name, limit=bounded_limit)
        return {
            "symbol_name": symbol_name,
            "count": len(refs),
            "references": [r.to_dict() for r in refs],
        }

    async def search_code_structure_handler(
        query: str,
        limit: int = 20,
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        ws = _get_workspace(context)
        bounded_limit = max(1, min(limit, 50))
        matches = code_service.search_code_structure(ws, query=query, limit=bounded_limit)
        return {
            "query": query,
            "count": len(matches),
            "results": matches,
        }

    # Definitions
    list_files_def = ToolDefinition(
        name="list_code_files",
        description="Discover and list source code files in the workspace matching supported languages.",
        parameters={
            "type": "object",
            "properties": {
                "subpath": {"type": "string", "description": "Relative directory path (default: '.')"},
                "max_files": {"type": "integer", "description": "Max files to return (default: 50, max: 200)"},
            },
            "required": [],
        },
    )

    get_struct_def = ToolDefinition(
        name="get_code_structure",
        description="Extract the structural symbol hierarchy (classes, functions, methods) of a file.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the source file"},
                "max_depth": {"type": "integer", "description": "Maximum nesting depth (default: 3, max: 5)"},
            },
            "required": ["path"],
        },
    )

    get_def_def = ToolDefinition(
        name="get_symbol_definition",
        description="Find the primary definition, signature, and location of a code symbol.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name or qualified name of the symbol"},
                "file_path": {"type": "string", "description": "Optional file path hint to narrow search"},
            },
            "required": ["name"],
        },
    )

    find_symbols_def = ToolDefinition(
        name="find_symbols",
        description="Search for symbols (functions, classes, interfaces) across workspace by name query or kind.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Substring to match in symbol name or qualified name"},
                "kind": {
                    "type": "string",
                    "description": "Optional symbol kind filter (e.g. 'class', 'function', 'method', 'interface')",
                },
                "file_path": {"type": "string", "description": "Optional file path to restrict search"},
                "limit": {"type": "integer", "description": "Maximum symbols to return (default: 20, max: 50)"},
            },
            "required": [],
        },
    )

    find_refs_def = ToolDefinition(
        name="find_references",
        description="Find syntactic callers, references, and imports of a symbol across the workspace.",
        parameters={
            "type": "object",
            "properties": {
                "symbol_name": {"type": "string", "description": "Name of the symbol to find references for"},
                "limit": {"type": "integer", "description": "Maximum references to return (default: 20, max: 50)"},
            },
            "required": ["symbol_name"],
        },
    )

    search_struct_def = ToolDefinition(
        name="search_code_structure",
        description="Search across symbol signatures, names, and docstrings in the codebase.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword or identifier to search"},
                "limit": {"type": "integer", "description": "Maximum results to return (default: 20, max: 50)"},
            },
            "required": ["query"],
        },
    )

    return [
        (list_files_def, list_code_files_handler),
        (get_struct_def, get_code_structure_handler),
        (get_def_def, get_symbol_definition_handler),
        (find_symbols_def, find_symbols_handler),
        (find_refs_def, find_references_handler),
        (search_struct_def, search_code_structure_handler),
    ]
