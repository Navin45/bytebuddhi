"""Security boundary unit tests for code intelligence operations."""

from pathlib import Path

import pytest

from app.application.code.in_memory_index import InMemoryCodeIndex
from app.application.code.intelligence_service import CodeIntelligenceService
from app.domain.exceptions.workspace_exceptions import (
    WorkspaceBoundaryError,
)
from app.domain.models.workspace import Workspace
from app.infrastructure.parser.tree_sitter_parser import TreeSitterCodeParser


@pytest.fixture
def workspace_dir(tmp_path: Path) -> Path:
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    return ws_dir


@pytest.fixture
def workspace(workspace_dir: Path) -> Workspace:
    return Workspace.create(root_path=str(workspace_dir), workspace_id="security_ws")


@pytest.fixture
def code_service() -> CodeIntelligenceService:
    return CodeIntelligenceService(
        parser=TreeSitterCodeParser(),
        index=InMemoryCodeIndex(),
    )


def test_path_traversal_outside_workspace_rejected(
    code_service: CodeIntelligenceService,
    workspace: Workspace,
    tmp_path: Path,
):
    outside_file = tmp_path / "secret.py"
    outside_file.write_text("SECRET_KEY = '12345'", encoding="utf-8")

    # Attempt to analyze file outside workspace via relative traversal
    with pytest.raises(WorkspaceBoundaryError):
        code_service.analyze_file(workspace, "../secret.py")

    with pytest.raises(WorkspaceBoundaryError):
        code_service.analyze_file(workspace, "../../secret.py")


def test_absolute_path_outside_workspace_rejected(
    code_service: CodeIntelligenceService,
    workspace: Workspace,
    tmp_path: Path,
):
    outside_file = tmp_path / "secret.py"
    outside_file.write_text("SECRET_KEY = '12345'", encoding="utf-8")

    with pytest.raises(WorkspaceBoundaryError):
        code_service.analyze_file(workspace, str(outside_file))


def test_symlink_escape_rejected_during_discovery(
    code_service: CodeIntelligenceService,
    workspace: Workspace,
    workspace_dir: Path,
    tmp_path: Path,
):
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "external.py").write_text("EXTERNAL = True", encoding="utf-8")

    # Create symlink inside workspace pointing outside
    link_path = workspace_dir / "link_to_outside"
    try:
        link_path.symlink_to(outside_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this environment without administrator privileges")

    discovered = code_service.discover_code_files(workspace)
    # External file via symlink escape should NOT be included in discovered files
    assert not any("external.py" in f for f in discovered)
