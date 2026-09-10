"""Unit tests for CommandPolicy risk classification and approval hooks."""

from unittest.mock import MagicMock

import pytest

from app.application.policy.command_policy import (
    CommandPolicy,
    CommandRiskLevel,
)
from app.application.policy.tool_policy import ToolPolicyEngine
from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import ToolCall
from app.domain.models.workspace import Workspace


def test_classify_read_only_commands():
    policy = CommandPolicy()
    assert policy.classify(["git", "status"]) == CommandRiskLevel.READ_ONLY
    assert policy.classify(["git", "diff"]) == CommandRiskLevel.READ_ONLY
    assert policy.classify(["ls", "-la"]) == CommandRiskLevel.READ_ONLY
    assert policy.classify("cat README.md") == CommandRiskLevel.READ_ONLY


def test_classify_modifying_commands():
    policy = CommandPolicy()
    assert policy.classify(["git", "commit", "-m", "fix"]) == CommandRiskLevel.MODIFYING
    assert policy.classify(["touch", "test.py"]) == CommandRiskLevel.MODIFYING


def test_classify_network_and_package_commands():
    policy = CommandPolicy()
    assert policy.classify(["pip", "install", "pytest"]) == CommandRiskLevel.NETWORK_OR_PACKAGE
    assert policy.classify(["npm", "run", "build"]) == CommandRiskLevel.NETWORK_OR_PACKAGE


def test_classify_interpreters_and_shells_as_high_risk():
    policy = CommandPolicy()
    assert policy.classify(["python", "-c", "print(1)"]) == CommandRiskLevel.HIGH_RISK
    assert policy.classify(["bash", "-c", "echo hello"]) == CommandRiskLevel.HIGH_RISK
    assert policy.classify(["sh", "script.sh"]) == CommandRiskLevel.HIGH_RISK
    assert policy.classify(["powershell.exe", "-Command", "Get-Process"]) == CommandRiskLevel.HIGH_RISK
    assert policy.classify(["node", "index.js"]) == CommandRiskLevel.HIGH_RISK


def test_classify_destructive_commands():
    policy = CommandPolicy()
    assert policy.classify("rm -rf /") == CommandRiskLevel.DESTRUCTIVE
    assert policy.classify("rm -rf /*") == CommandRiskLevel.DESTRUCTIVE
    assert policy.classify("del /s /q c:\\") == CommandRiskLevel.DESTRUCTIVE
    assert policy.classify(":(){ :|:& };:") == CommandRiskLevel.DESTRUCTIVE


def test_destructive_commands_are_blocked_unconditionally():
    policy = CommandPolicy(allow_high_risk=True)  # even with allow_high_risk
    allowed, risk, reason = policy.validate_command("rm -rf /")
    assert not allowed
    assert risk == CommandRiskLevel.DESTRUCTIVE
    assert "prohibited" in reason.lower()


def test_high_risk_commands_blocked_by_default():
    policy = CommandPolicy(allow_high_risk=False)
    allowed, risk, reason = policy.validate_command(["python", "-c", "print(1)"])
    assert not allowed
    assert risk == CommandRiskLevel.HIGH_RISK
    assert "high-risk" in reason.lower()


def test_high_risk_commands_with_approval_hook():
    mock_hook = MagicMock()
    mock_hook.is_approved.return_value = True

    policy = CommandPolicy(approval_hook=mock_hook)
    allowed, risk, reason = policy.validate_command(["python", "-c", "print(1)"])
    assert allowed
    assert risk == CommandRiskLevel.HIGH_RISK
    assert reason is None
    mock_hook.is_approved.assert_called_once()

    # When hook denies
    mock_hook.is_approved.return_value = False
    allowed, risk, reason = policy.validate_command(["python", "-c", "print(1)"])
    assert not allowed
    assert "requires approval" in reason.lower()


@pytest.mark.asyncio
async def test_tool_policy_engine_validates_run_command(tmp_path):
    workspace = Workspace.create(root_path=tmp_path)
    engine = ToolPolicyEngine(command_policy=CommandPolicy(allow_high_risk=True))
    context = ToolExecutionContext(run_id="run_1", tool_call_id="call_1", workspace=workspace)

    # Valid read-only command
    call_valid = ToolCall(id="call_1", name="run_command", arguments={"command": ["git", "status"]})
    allowed, reason = await engine.authorize_tool_call(call_valid, context)
    assert allowed
    assert reason is None

    # Invalid command with escaping cwd
    call_invalid_cwd = ToolCall(
        id="call_2",
        name="run_command",
        arguments={"command": ["git", "status"], "cwd": "../../outside"},
    )
    allowed, reason = await engine.authorize_tool_call(call_invalid_cwd, context)
    assert not allowed
    assert "resolves outside workspace" in reason

    # Filesystem tool path escape
    call_fs = ToolCall(id="call_3", name="read_file", arguments={"path": "../../etc/passwd"})
    allowed, reason = await engine.authorize_tool_call(call_fs, context)
    assert not allowed
    assert "resolves outside workspace" in reason
