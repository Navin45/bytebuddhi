"""Unit tests for Workspace domain entity and boundary enforcement."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

from app.domain.exceptions.workspace_exceptions import WorkspaceBoundaryError
from app.domain.models.workspace import Workspace


@pytest.fixture
def temp_workspace() -> Workspace:
    """Create a temporary directory and workspace for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Workspace.create(root_path=tmpdir, workspace_id="test_ws")
        yield ws


def test_workspace_initialization(temp_workspace: Workspace):
    assert temp_workspace.workspace_id == "test_ws"
    assert temp_workspace.root_path.is_absolute()
    assert temp_workspace.root_path.exists()
    assert temp_workspace.allowed_paths == [temp_workspace.root_path]


def test_resolve_valid_relative_path(temp_workspace: Workspace):
    target = temp_workspace.resolve_path("file.txt")
    expected = (temp_workspace.root_path / "file.txt").resolve()
    assert target == expected
    assert temp_workspace.is_safe_path("file.txt")


def test_resolve_nested_relative_path(temp_workspace: Workspace):
    target = temp_workspace.resolve_path("src/components/button.tsx")
    expected = (temp_workspace.root_path / "src" / "components" / "button.tsx").resolve()
    assert target == expected
    assert temp_workspace.is_safe_path("src/components/button.tsx")


def test_resolve_valid_absolute_path_inside_root(temp_workspace: Workspace):
    subpath = temp_workspace.root_path / "data" / "items.json"
    resolved = temp_workspace.resolve_path(subpath)
    assert resolved == subpath.resolve()
    assert temp_workspace.is_safe_path(subpath)


def test_reject_directory_traversal_double_dot(temp_workspace: Workspace):
    with pytest.raises(WorkspaceBoundaryError) as exc_info:
        temp_workspace.resolve_path("../../etc/passwd")
    assert "outside workspace boundary" in str(exc_info.value)
    assert not temp_workspace.is_safe_path("../../etc/passwd")


def test_reject_directory_traversal_nested_escape(temp_workspace: Workspace):
    with pytest.raises(WorkspaceBoundaryError):
        temp_workspace.resolve_path("sub/dir/../../../../windows/system32")


def test_reject_absolute_path_outside_root(temp_workspace: Workspace):
    outside_path = Path("/etc/passwd") if sys.platform != "win32" else Path("C:/Windows/System32/calc.exe")
    with pytest.raises(WorkspaceBoundaryError):
        temp_workspace.resolve_path(outside_path)
    assert not temp_workspace.is_safe_path(outside_path)


def test_reject_null_byte_in_path(temp_workspace: Workspace):
    with pytest.raises(WorkspaceBoundaryError) as exc:
        temp_workspace.resolve_path("valid/path\0something")
    assert "Null bytes" in str(exc.value)


def test_symlink_pointing_outside_workspace_rejected():
    """Verify that a symlink pointing outside the workspace root is rejected."""
    with tempfile.TemporaryDirectory() as outside_dir, tempfile.TemporaryDirectory() as ws_dir:
        outside_file = Path(outside_dir) / "secret.txt"
        outside_file.write_text("classified data")

        ws = Workspace.create(root_path=ws_dir)
        symlink_path = Path(ws_dir) / "link_to_outside"

        try:
            os.symlink(outside_file, symlink_path)
            with pytest.raises(WorkspaceBoundaryError) as exc:
                ws.resolve_path("link_to_outside")
            assert "outside workspace boundary" in str(exc.value)
            assert not ws.is_safe_path("link_to_outside")
        except (OSError, NotImplementedError):
            # On Windows without developer mode/admin rights, test using mocked resolve
            pass


def test_mocked_symlink_resolution_outside_workspace(temp_workspace: Workspace, monkeypatch: pytest.MonkeyPatch):
    """Verify that if Path.resolve() resolves to an external path (e.g. symlink/junction), it is rejected."""
    original_resolve = Path.resolve

    def fake_resolve(self: Path, *args, **kwargs) -> Path:
        if self.name == "junction_to_c_drive":
            return Path("C:/Windows/System32").resolve() if sys.platform == "win32" else Path("/etc/passwd").resolve()
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fake_resolve)
    with pytest.raises(WorkspaceBoundaryError):
        temp_workspace.resolve_path("junction_to_c_drive")
    assert not temp_workspace.is_safe_path("junction_to_c_drive")


def test_symlink_pointing_inside_workspace_allowed():
    """Verify that a symlink pointing to another location inside the workspace is allowed."""
    with tempfile.TemporaryDirectory() as ws_dir:
        real_file = Path(ws_dir) / "original.txt"
        real_file.write_text("original content")

        ws = Workspace.create(root_path=ws_dir)
        symlink_path = Path(ws_dir) / "link_internal.txt"

        try:
            os.symlink(real_file, symlink_path)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported in current test environment")

        resolved = ws.resolve_path("link_internal.txt")
        assert resolved == real_file.resolve()
        assert ws.is_safe_path("link_internal.txt")


def test_allowed_paths_extension():
    """Verify that explicitly configured allowed paths allow resolution."""
    with tempfile.TemporaryDirectory() as dir1, tempfile.TemporaryDirectory() as dir2:
        ws = Workspace.create(root_path=dir1, allowed_paths=[dir2])
        resolved2 = ws.resolve_path(Path(dir2) / "shared.txt")
        assert resolved2 == (Path(dir2) / "shared.txt").resolve()
