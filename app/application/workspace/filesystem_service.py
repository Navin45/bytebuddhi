"""Filesystem service providing safe, bounded workspace filesystem operations."""

from typing import Any

import aiofiles
import aiofiles.os

from app.domain.exceptions.workspace_exceptions import (
    FileAlreadyExistsWorkspaceError,
    FileNotFoundWorkspaceError,
    WorkspaceBoundaryError,
)
from app.domain.models.workspace import Workspace
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class FilesystemService:
    """Provides controlled filesystem operations constrained to a workspace root."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    async def list_directory(
        self,
        path: str = ".",
        max_entries: int = 200,
        include_hidden: bool = False,
    ) -> list[dict[str, Any]]:
        """List contents of a directory inside the workspace.

        Args:
            path: Path relative to workspace root (defaults to ".").
            max_entries: Maximum number of directory entries to return.
            include_hidden: Whether to include dotfiles/hidden entries.

        Returns:
            list[dict[str, Any]]: Sorted list of file/directory descriptor dicts.
        """
        resolved = self.workspace.resolve_path(path)
        if not resolved.exists():
            raise FileNotFoundWorkspaceError(str(self.workspace.get_relative_path(resolved)))
        if not resolved.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {self.workspace.get_relative_path(resolved)}")

        entries: list[dict[str, Any]] = []
        try:
            # Sort entries: directories first, then alphabetical
            all_items = sorted(
                resolved.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )

            for item in all_items:
                if not include_hidden and item.name.startswith("."):
                    continue

                is_dir = item.is_dir()
                size = 0 if is_dir else item.stat().st_size
                rel_path = self.workspace.get_relative_path(item)

                entries.append(
                    {
                        "name": item.name,
                        "type": "directory" if is_dir else "file",
                        "size_bytes": size,
                        "path": str(rel_path).replace("\\", "/"),
                    }
                )

                if len(entries) >= max_entries:
                    break

            return entries

        except WorkspaceBoundaryError:
            raise
        except Exception as e:
            logger.error("Error listing directory", path=str(resolved), error=str(e))
            raise

    async def read_file(
        self,
        path: str,
        offset: int = 0,
        limit: int = 64 * 1024,
    ) -> dict[str, Any]:
        """Read text file content safely within the workspace.

        Args:
            path: Path relative to workspace root.
            offset: Byte offset to begin reading from.
            limit: Maximum bytes to read.

        Returns:
            dict[str, Any]: File content and windowing metadata.
        """
        resolved = self.workspace.resolve_path(path)
        if not resolved.exists():
            raise FileNotFoundWorkspaceError(str(self.workspace.get_relative_path(resolved)))
        if resolved.is_dir():
            raise IsADirectoryError(f"Target is a directory, not a file: {self.workspace.get_relative_path(resolved)}")

        total_bytes = resolved.stat().st_size

        try:
            async with aiofiles.open(resolved, mode="rb") as f:
                if offset > 0:
                    await f.seek(offset)
                raw_data = await f.read(limit)

            text_content = raw_data.decode("utf-8", errors="replace")
            bytes_read = len(raw_data)
            is_truncated = (offset + bytes_read) < total_bytes

            return {
                "path": str(self.workspace.get_relative_path(resolved)).replace("\\", "/"),
                "content": text_content,
                "total_bytes": total_bytes,
                "offset": offset,
                "bytes_read": bytes_read,
                "is_truncated": is_truncated,
            }

        except Exception as e:
            logger.error("Error reading file", path=str(resolved), error=str(e))
            raise

    async def write_file(
        self,
        path: str,
        content: str,
        create_parents: bool = True,
        overwrite: bool = True,
    ) -> dict[str, Any]:
        """Write content to a file inside the workspace safely.

        Args:
            path: Path relative to workspace root.
            content: Text content to write.
            create_parents: Create parent directories if they do not exist.
            overwrite: Allow overwriting existing file.

        Returns:
            dict[str, Any]: Result metadata.
        """
        resolved = self.workspace.resolve_path(path)
        existed = resolved.exists()

        if existed and not overwrite:
            raise FileAlreadyExistsWorkspaceError(str(self.workspace.get_relative_path(resolved)))

        try:
            if create_parents:
                resolved.parent.mkdir(parents=True, exist_ok=True)

            # Atomic write via temporary sibling file
            tmp_file = resolved.parent / f".tmp_{resolved.name}"
            async with aiofiles.open(tmp_file, mode="w", encoding="utf-8") as f:
                await f.write(content)

            # Replace atomic rename
            await aiofiles.os.replace(tmp_file, resolved)

            bytes_written = len(content.encode("utf-8"))
            return {
                "path": str(self.workspace.get_relative_path(resolved)).replace("\\", "/"),
                "bytes_written": bytes_written,
                "created": not existed,
            }

        except Exception as e:
            logger.error("Error writing file", path=str(resolved), error=str(e))
            raise

    async def create_directory(self, path: str, parents: bool = True) -> dict[str, Any]:
        """Create a directory within the workspace.

        Args:
            path: Path relative to workspace root.
            parents: Whether to create parent directories if missing.

        Returns:
            dict[str, Any]: Creation result.
        """
        resolved = self.workspace.resolve_path(path)
        resolved.mkdir(parents=parents, exist_ok=True)
        return {
            "path": str(self.workspace.get_relative_path(resolved)).replace("\\", "/"),
            "created": True,
        }
