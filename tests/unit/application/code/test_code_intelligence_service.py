"""Unit tests for CodeIntelligenceService."""

from pathlib import Path

import pytest

from app.application.code.in_memory_index import InMemoryCodeIndex
from app.application.code.intelligence_service import CodeIntelligenceService
from app.domain.models.workspace import Workspace
from app.infrastructure.parser.tree_sitter_parser import TreeSitterCodeParser


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Workspace:
    return Workspace.create(root_path=str(tmp_path), workspace_id="test_ws")


@pytest.fixture
def service() -> CodeIntelligenceService:
    parser = TreeSitterCodeParser()
    index = InMemoryCodeIndex()
    return CodeIntelligenceService(parser=parser, index=index)


def test_canonical_file_identity(service: CodeIntelligenceService, temp_workspace: Workspace, tmp_path: Path) -> None:
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    target_file = tmp_path / "foo.py"
    target_file.write_text("class Foo:\n    pass\n", encoding="utf-8")

    # Resolve from various representations
    _, c1 = service.get_canonical_relative_path(temp_workspace, "./foo.py")
    _, c2 = service.get_canonical_relative_path(temp_workspace, "foo.py")
    _, c3 = service.get_canonical_relative_path(temp_workspace, "subdir/../foo.py")
    _, c4 = service.get_canonical_relative_path(temp_workspace, target_file)

    assert c1 == "foo.py"
    assert c2 == "foo.py"
    assert c3 == "foo.py"
    assert c4 == "foo.py"

    # Verify indexing creates exactly one entry
    s1 = service.analyze_file(temp_workspace, "./foo.py")
    s2 = service.analyze_file(temp_workspace, "subdir/../foo.py")

    assert s1 is s2  # Cache hit on canonical path!
    assert len(service.index.get_all_structures()) == 1


def test_discovery_and_exclusion_rules(
    service: CodeIntelligenceService, temp_workspace: Workspace, tmp_path: Path
) -> None:
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / "util.ts").write_text("export const x = 1;", encoding="utf-8")
    (tmp_path / "doc.txt").write_text("text doc", encoding="utf-8")

    # Excluded directories
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config.py").write_text("git config", encoding="utf-8")

    node_dir = tmp_path / "node_modules"
    node_dir.mkdir()
    (node_dir / "dep.js").write_text("dep code", encoding="utf-8")

    discovered = service.discover_code_files(temp_workspace)
    assert "main.py" in discovered
    assert "util.ts" in discovered
    assert "doc.txt" not in discovered  # unsupported
    assert ".git/config.py" not in discovered
    assert "node_modules/dep.js" not in discovered


def test_content_hash_cache_lifecycle(
    service: CodeIntelligenceService, temp_workspace: Workspace, tmp_path: Path
) -> None:
    f = tmp_path / "calc.py"
    f.write_text("def add(a, b): return a + b\n", encoding="utf-8")

    # Initial parse
    struct1 = service.analyze_file(temp_workspace, "calc.py")
    assert struct1.content_hash != ""
    assert len(struct1.symbols) == 1

    # Same content -> cache hit
    struct2 = service.analyze_file(temp_workspace, "calc.py")
    assert struct2 is struct1

    # Content changed -> cache invalidation and reparse
    f.write_text("def add(a, b): return a + b\ndef sub(a, b): return a - b\n", encoding="utf-8")
    struct3 = service.analyze_file(temp_workspace, "calc.py")
    assert struct3 is not struct1
    assert len(struct3.symbols) == 2
    assert struct3.content_hash != struct1.content_hash

    # Invalidate / deletion
    assert service.invalidate_file(temp_workspace, "calc.py") is True
    assert service.index.get("calc.py") is None


def test_language_identity_change_invalidates(
    service: CodeIntelligenceService, temp_workspace: Workspace, tmp_path: Path
) -> None:
    # Rename/replace file extension
    f = tmp_path / "script"
    f.write_text("class Temp:\n    pass\n", encoding="utf-8")

    struct = service.analyze_file(temp_workspace, "script")
    assert struct.language == "other"

    # Now with .py
    f_py = tmp_path / "script.py"
    f_py.write_text("class Temp:\n    pass\n", encoding="utf-8")
    struct_py = service.analyze_file(temp_workspace, "script.py")
    assert struct_py.language == "python"
    assert len(struct_py.symbols) == 1


def test_resource_bounding_max_file_bytes(temp_workspace: Workspace, tmp_path: Path) -> None:
    parser = TreeSitterCodeParser()
    index = InMemoryCodeIndex()
    # Set limit to 100 bytes
    bounded_service = CodeIntelligenceService(parser=parser, index=index, max_file_bytes=100)

    f = tmp_path / "large.py"
    f.write_text("#" * 500 + "\nclass Large:\n    pass\n", encoding="utf-8")

    struct = bounded_service.analyze_file(temp_workspace, "large.py")
    assert len(struct.diagnostics) == 1
    assert "exceeds maximum size limit" in struct.diagnostics[0].message
    assert len(struct.symbols) == 0  # Not parsed


def test_resource_bounding_max_total_bytes_and_time(temp_workspace: Workspace, tmp_path: Path) -> None:
    parser = TreeSitterCodeParser()
    index = InMemoryCodeIndex()
    # Set total bytes limit to 50 bytes
    bounded_service = CodeIntelligenceService(
        parser=parser,
        index=index,
        max_file_bytes=1000,
        max_total_bytes=50,
        max_analysis_time=0.0001,  # very small time limit
    )

    (tmp_path / "f1.py").write_text("x = 1\n" * 10, encoding="utf-8")
    (tmp_path / "f2.py").write_text("y = 2\n" * 10, encoding="utf-8")

    results = bounded_service.analyze_workspace(temp_workspace)
    # Bounding stops before loading all files
    assert len(results) <= 1


def test_get_code_structure_hierarchical_view(
    service: CodeIntelligenceService, temp_workspace: Workspace, tmp_path: Path
) -> None:
    f = tmp_path / "tree.py"
    f.write_text(
        "class Container:\n    def run(self):\n        pass\n",
        encoding="utf-8",
    )

    tree_dict = service.get_code_structure(temp_workspace, "tree.py")
    assert tree_dict["file_path"] == "tree.py"
    assert len(tree_dict["symbols"]) == 1

    root_sym = tree_dict["symbols"][0]
    assert root_sym["name"] == "Container"
    assert len(root_sym["children"]) == 1
    assert root_sym["children"][0]["name"] == "run"
