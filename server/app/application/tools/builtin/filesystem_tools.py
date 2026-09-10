"""Builtin filesystem tools constrained to workspace boundaries."""

from typing import Any

from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import ToolDefinition
from app.application.workspace.filesystem_service import FilesystemService


def create_filesystem_tools(
    default_fs_service: FilesystemService | None = None,
) -> list[tuple[ToolDefinition, Any]]:
    """Create and return tool definitions and handlers for filesystem operations.

    If a ToolExecutionContext is provided at invocation, its workspace is used dynamically.
    """

    async def list_directory_handler(
        path: str = ".",
        max_entries: int = 200,
        include_hidden: bool = False,
        context: ToolExecutionContext | None = None,
    ) -> list[dict[str, Any]]:
        fs = FilesystemService(context.workspace) if context else default_fs_service
        if not fs:
            raise ValueError("No workspace available for list_directory")
        return await fs.list_directory(path=path, max_entries=max_entries, include_hidden=include_hidden)

    async def read_file_handler(
        path: str,
        offset: int = 0,
        limit: int = 64 * 1024,
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        fs = FilesystemService(context.workspace) if context else default_fs_service
        if not fs:
            raise ValueError("No workspace available for read_file")
        return await fs.read_file(path=path, offset=offset, limit=limit)

    async def write_file_handler(
        path: str,
        content: str,
        create_parents: bool = True,
        overwrite: bool = True,
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        fs = FilesystemService(context.workspace) if context else default_fs_service
        if not fs:
            raise ValueError("No workspace available for write_file")
        return await fs.write_file(path=path, content=content, create_parents=create_parents, overwrite=overwrite)

    async def create_directory_handler(
        path: str,
        parents: bool = True,
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        fs = FilesystemService(context.workspace) if context else default_fs_service
        if not fs:
            raise ValueError("No workspace available for create_directory")
        return await fs.create_directory(path=path, parents=parents)

    # Definitions
    list_dir_def = ToolDefinition(
        name="list_directory",
        description="List files and subdirectories within the workspace directory.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to list (defaults to '.')"},
                "max_entries": {"type": "integer", "description": "Maximum entries to return (default: 200)"},
                "include_hidden": {"type": "boolean", "description": "Whether to include hidden files/dotfiles"},
            },
            "required": [],
        },
    )

    read_file_def = ToolDefinition(
        name="read_file",
        description="Read file contents within the workspace safely with windowing.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file to read"},
                "offset": {"type": "integer", "description": "Byte offset to start reading from"},
                "limit": {"type": "integer", "description": "Maximum bytes to read (default: 64KB)"},
            },
            "required": ["path"],
        },
    )

    write_file_def = ToolDefinition(
        name="write_file",
        description="Write content to a file inside the workspace safely.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file to write"},
                "content": {"type": "string", "description": "Text content to write"},
                "create_parents": {"type": "boolean", "description": "Create parent directories if missing"},
                "overwrite": {"type": "boolean", "description": "Overwrite file if it already exists"},
            },
            "required": ["path", "content"],
        },
    )

    create_dir_def = ToolDefinition(
        name="create_directory",
        description="Create a directory path within the workspace.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path of directory to create"},
                "parents": {"type": "boolean", "description": "Create intermediate parent directories"},
            },
            "required": ["path"],
        },
    )

    return [
        (list_dir_def, list_directory_handler),
        (read_file_def, read_file_handler),
        (write_file_def, write_file_handler),
        (create_dir_def, create_directory_handler),
    ]
