"""Unit tests for CommandExecutor."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.application.execution.command_executor import CommandExecutor
from app.application.policy.command_policy import CommandPolicy
from app.application.ports.output.execution.process_manager import (
    ProcessStatus,
)
from app.application.ports.output.storage.artifact_store import ArtifactStore
from app.domain.exceptions.workspace_exceptions import (
    CommandBlockedError,
    WorkspaceBoundaryError,
)
from app.domain.models.environment_policy import EnvironmentPolicy
from app.domain.models.workspace import Workspace
from app.infrastructure.execution.local_process_manager import LocalProcessManager


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace.create(root_path=tmp_path, workspace_id="ws_cmd_test")


@pytest.fixture
def command_executor(workspace: Workspace) -> CommandExecutor:
    pm = LocalProcessManager()
    policy = CommandPolicy(allow_high_risk=True)
    env_policy = EnvironmentPolicy()
    return CommandExecutor(
        process_manager=pm,
        workspace=workspace,
        command_policy=policy,
        environment_policy=env_policy,
    )


@pytest.mark.asyncio
async def test_command_executor_successful_argv(command_executor: CommandExecutor):
    cmd = [sys.executable, "-c", "print('executor success')"]
    result = await command_executor.execute(command=cmd)

    assert result.exit_code == 0
    assert result.status == ProcessStatus.COMPLETED
    assert "executor success" in result.stdout_preview


@pytest.mark.asyncio
async def test_command_executor_blocks_destructive(command_executor: CommandExecutor):
    with pytest.raises(CommandBlockedError) as exc_info:
        await command_executor.execute(command_str="rm -rf /")
    assert "Destructive" in str(exc_info.value)


@pytest.mark.asyncio
async def test_command_executor_rejects_escaping_cwd(command_executor: CommandExecutor):
    with pytest.raises(WorkspaceBoundaryError):
        await command_executor.execute(
            command=[sys.executable, "-c", "print(1)"],
            cwd="../../outside_workspace",
        )


@pytest.mark.asyncio
async def test_command_executor_archives_to_artifact_store(workspace: Workspace):
    mock_artifact_store = AsyncMock(spec=ArtifactStore)
    mock_artifact_store.save_artifact.return_value = "storage/artifacts/archived.log"

    pm = LocalProcessManager()
    policy = CommandPolicy(allow_high_risk=True)

    executor = CommandExecutor(
        process_manager=pm,
        workspace=workspace,
        command_policy=policy,
        artifact_store=mock_artifact_store,
    )

    from app.application.tools.context import ToolExecutionContext
    from tests.helpers.execution import trusted_execution_context

    ctx = ToolExecutionContext.from_execution(
        trusted_execution_context(workspace_id=workspace.workspace_id),
        tool_call_id="cmd_archive",
        workspace=workspace,
    )

    cmd = [sys.executable, "-c", "print('stream to archive')"]
    result = await executor.execute(command=cmd, context=ctx)

    assert result.exit_code == 0
    assert result.stdout_ref == "storage/artifacts/archived.log"
    mock_artifact_store.save_artifact.assert_called()
