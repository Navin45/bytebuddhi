"""Unit tests for Phase 2 filesystem and command tools integrated with ToolExecutor."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.ports.output.execution.process_manager import (
    ProcessResult,
    ProcessStatus,
)
from app.application.tools.builtin.command_tools import create_command_tool
from app.application.tools.builtin.filesystem_tools import create_filesystem_tools
from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import ToolCall
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry
from app.domain.models.workspace import Workspace


@pytest.fixture
def workspace(tmp_path) -> Workspace:
    return Workspace.create(root_path=tmp_path, workspace_id="ws_tools_test")


@pytest.fixture
def context(workspace: Workspace) -> ToolExecutionContext:
    return ToolExecutionContext(run_id="run_100", tool_call_id="call_100", workspace=workspace)


@pytest.mark.asyncio
async def test_filesystem_tools_through_executor(workspace: Workspace, context: ToolExecutionContext):
    registry = ToolRegistry()
    fs_tools = create_filesystem_tools()
    for defn, handler in fs_tools:
        registry.register(defn, handler)

    executor = ToolExecutor(registry)

    # 1. Write file
    write_call = ToolCall(
        id="call_1",
        name="write_file",
        arguments={"path": "greeting.txt", "content": "Hello World!"},
    )
    res_write = await executor.execute(write_call, context=context)
    assert not res_write.is_error
    assert "greeting.txt" in res_write.content

    # 2. Read file
    read_call = ToolCall(id="call_2", name="read_file", arguments={"path": "greeting.txt"})
    res_read = await executor.execute(read_call, context=context)
    assert not res_read.is_error
    assert "Hello World!" in res_read.content

    # 3. Create directory
    dir_call = ToolCall(id="call_3", name="create_directory", arguments={"path": "src/sub"})
    res_dir = await executor.execute(dir_call, context=context)
    assert not res_dir.is_error

    # 4. List directory
    list_call = ToolCall(id="call_4", name="list_directory", arguments={"path": "."})
    res_list = await executor.execute(list_call, context=context)
    assert not res_list.is_error
    assert "greeting.txt" in res_list.content
    assert "src" in res_list.content


@pytest.mark.asyncio
async def test_command_tool_through_executor(context: ToolExecutionContext):
    registry = ToolRegistry()
    mock_cmd_executor = MagicMock()
    mock_cmd_executor.execute = AsyncMock(
        return_value=ProcessResult(
            execution_id="exec_999",
            exit_code=0,
            status=ProcessStatus.COMPLETED,
            duration_seconds=0.15,
            stdout_preview="hello stdout",
            stderr_preview="",
            stdout_bytes=12,
            stderr_bytes=0,
            stdout_ref="storage/artifacts/exec_999_stdout.log",
        )
    )

    defn, handler = create_command_tool(mock_cmd_executor)
    registry.register(defn, handler)

    executor = ToolExecutor(registry)
    call = ToolCall(
        id="call_cmd",
        name="run_command",
        arguments={"command": ["echo", "hello stdout"]},
    )

    res = await executor.execute(call, context=context)
    assert not res.is_error
    assert "exec_999" in res.content
    assert "hello stdout" in res.content
    assert "storage/artifacts/exec_999_stdout.log" in res.content
