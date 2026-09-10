"""Unit tests for FilesystemService."""

import pytest

from app.application.workspace.filesystem_service import FilesystemService
from app.domain.exceptions.workspace_exceptions import (
    FileAlreadyExistsWorkspaceError,
    FileNotFoundWorkspaceError,
    WorkspaceBoundaryError,
)
from app.domain.models.workspace import Workspace


@pytest.fixture
def workspace(tmp_path) -> Workspace:
    return Workspace.create(root_path=tmp_path, workspace_id="test_fs_ws")


@pytest.fixture
def fs_service(workspace: Workspace) -> FilesystemService:
    return FilesystemService(workspace=workspace)


@pytest.mark.asyncio
async def test_write_and_read_file(fs_service: FilesystemService, workspace: Workspace):
    result = await fs_service.write_file("hello.txt", "Hello, ByteBuddhi!")
    assert result["created"]
    assert result["bytes_written"] > 0
    assert (workspace.root_path / "hello.txt").exists()

    read_result = await fs_service.read_file("hello.txt")
    assert read_result["content"] == "Hello, ByteBuddhi!"
    assert read_result["total_bytes"] == len(b"Hello, ByteBuddhi!")
    assert not read_result["is_truncated"]


@pytest.mark.asyncio
async def test_write_file_creates_parents(fs_service: FilesystemService, workspace: Workspace):
    await fs_service.write_file("nested/sub/deep/file.py", "print('nested')")
    assert (workspace.root_path / "nested" / "sub" / "deep" / "file.py").exists()

    read_result = await fs_service.read_file("nested/sub/deep/file.py")
    assert read_result["content"] == "print('nested')"


@pytest.mark.asyncio
async def test_write_file_overwrite_prevention(fs_service: FilesystemService):
    await fs_service.write_file("locked.txt", "initial")
    with pytest.raises(FileAlreadyExistsWorkspaceError):
        await fs_service.write_file("locked.txt", "new", overwrite=False)


@pytest.mark.asyncio
async def test_read_file_windowing(fs_service: FilesystemService):
    long_content = "0123456789" * 100  # 1000 chars
    await fs_service.write_file("long.txt", long_content)

    # Read slice with offset and limit
    window = await fs_service.read_file("long.txt", offset=10, limit=20)
    assert window["content"] == ("0123456789" * 100)[10:30]
    assert window["offset"] == 10
    assert window["bytes_read"] == 20
    assert window["is_truncated"]


@pytest.mark.asyncio
async def test_read_nonexistent_file_raises(fs_service: FilesystemService):
    with pytest.raises(FileNotFoundWorkspaceError):
        await fs_service.read_file("does_not_exist.txt")


@pytest.mark.asyncio
async def test_list_directory_sorting_and_filtering(fs_service: FilesystemService):
    await fs_service.write_file("z_file.txt", "z")
    await fs_service.write_file("a_file.txt", "a")
    await fs_service.create_directory("b_dir")
    await fs_service.write_file(".hidden", "secret")

    # Without hidden
    entries = await fs_service.list_directory(".", include_hidden=False)
    names = [e["name"] for e in entries]
    assert ".hidden" not in names
    # Directories appear first
    assert entries[0]["name"] == "b_dir"
    assert entries[0]["type"] == "directory"

    # With hidden
    entries_with_hidden = await fs_service.list_directory(".", include_hidden=True)
    names_all = [e["name"] for e in entries_with_hidden]
    assert ".hidden" in names_all


@pytest.mark.asyncio
async def test_filesystem_boundary_traversal_rejected(fs_service: FilesystemService):
    with pytest.raises(WorkspaceBoundaryError):
        await fs_service.read_file("../../etc/passwd")

    with pytest.raises(WorkspaceBoundaryError):
        await fs_service.write_file("../escape.txt", "malicious")

    with pytest.raises(WorkspaceBoundaryError):
        await fs_service.list_directory("../..")
