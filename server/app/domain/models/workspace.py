"""Workspace domain entity representing a bounded filesystem root."""

from pathlib import Path
from typing import Any
from uuid import uuid4

from app.domain.exceptions.workspace_exceptions import WorkspaceBoundaryError


class Workspace:
    """Represents a bounded filesystem workspace for an agent."""

    def __init__(
        self,
        workspace_id: str,
        root_path: str | Path,
        name: str | None = None,
        allowed_paths: list[str | Path] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.workspace_id = workspace_id
        self.name = name or f"workspace-{workspace_id}"
        self.root_path = Path(root_path).resolve()
        self.metadata = metadata or {}

        # Allowed paths always includes root_path
        self.allowed_paths: list[Path] = [self.root_path]
        if allowed_paths:
            for p in allowed_paths:
                resolved = Path(p).resolve()
                if resolved not in self.allowed_paths:
                    self.allowed_paths.append(resolved)

    @classmethod
    def create(
        cls,
        root_path: str | Path,
        workspace_id: str | None = None,
        name: str | None = None,
        allowed_paths: list[str | Path] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Workspace":
        """Factory method to create a workspace with auto-generated ID if omitted."""
        ws_id = workspace_id or f"ws_{uuid4().hex[:12]}"
        return cls(
            workspace_id=ws_id,
            root_path=root_path,
            name=name,
            allowed_paths=allowed_paths,
            metadata=metadata,
        )

    def resolve_path(self, target_path: str | Path) -> Path:
        """Safely resolve a path against the workspace root.

        Enforces that the resolved canonical path (with symlinks and junctions followed)
        remains strictly inside the workspace root or one of the explicitly allowed paths.

        Args:
            target_path: Relative subpath or absolute path.

        Returns:
            Path: Canonical, resolved Path safely inside the workspace boundary.

        Raises:
            WorkspaceBoundaryError: If path escapes root via traversal, absolute escaping,
                                   or symlinks/junctions pointing outside.
        """
        raw_str = str(target_path).strip()
        if "\0" in raw_str:
            raise WorkspaceBoundaryError(
                "Null bytes in path are prohibited", path=raw_str, root_path=str(self.root_path)
            )

        path_obj = Path(raw_str)

        # If relative, anchor to root_path; if absolute, evaluate directly
        candidate = path_obj if path_obj.is_absolute() else self.root_path / path_obj

        # Fully resolve canonical path, resolving '.' and '..' and symlinks/junctions
        try:
            resolved = candidate.resolve()
        except (ValueError, RuntimeError) as e:
            raise WorkspaceBoundaryError(
                f"Failed to resolve path: {e!s}", path=raw_str, root_path=str(self.root_path)
            ) from e

        # Verify whether the canonical target lies within any allowed path
        is_allowed = any(self._is_subpath(resolved, allowed_root) for allowed_root in self.allowed_paths)
        if not is_allowed:
            raise WorkspaceBoundaryError(
                f"Access denied: path '{raw_str}' resolves outside workspace boundary '{self.root_path}'",
                path=str(resolved),
                root_path=str(self.root_path),
            )

        return resolved

    def is_safe_path(self, target_path: str | Path) -> bool:
        """Check if a path safely resolves inside the workspace without raising an error."""
        try:
            self.resolve_path(target_path)
            return True
        except WorkspaceBoundaryError:
            return False

    def get_relative_path(self, target_path: Path) -> Path:
        """Get relative path from workspace root if inside, or return absolute path."""
        resolved = target_path.resolve()
        try:
            return resolved.relative_to(self.root_path)
        except ValueError:
            return resolved

    @staticmethod
    def _is_subpath(child: Path, parent: Path) -> bool:
        """Check if child is equal to or inside parent."""
        try:
            child.relative_to(parent)
            return True
        except ValueError:
            return False

    def __repr__(self) -> str:
        return f"<Workspace id={self.workspace_id} root={self.root_path}>"
