"""Unit tests for AgentContextProjector."""

import pytest

from app.application.agent.context_projector import AgentContextProjector
from app.domain.exceptions.execution_exceptions import ExecutionContextRequired
from app.domain.models.agent import AgentDefinition, AgentRole, AgentTask, MultiAgentConfig
from tests.helpers.execution import trusted_execution_context


def test_context_projector_minimal_context_selection():
    """Verify context projector builds structured subtask prompt with task info and inputs."""
    projector = AgentContextProjector()

    definition = AgentDefinition(
        id="reviewer",
        name="Review Specialist",
        description="Audits code",
        role=AgentRole.REVIEWER,
        system_prompt="Audit code carefully.",
    )

    task = AgentTask(
        task_id="task_audit_1",
        agent_id="reviewer",
        description="Check pull request #42 for potential race conditions.",
        expected_output="Bullet list of identified concurrency issues.",
        input_data={"pr_number": 42, "repo": "bytebuddhi"},
    )

    parent_execution = trusted_execution_context(
        user_id="alice",
        project_id="proj_123",
        conversation_id="conv_456",
        run_id="parent_run_001",
    )
    parent_meta = {
        "user_id": "attacker",
        "project_id": "proj_evil",
        "approved_actions": ["github_create_issue"],
        "approval_granted": True,
        "raw_secret": "sensitive_token",
    }

    messages, metadata = projector.project_child_context(
        task=task,
        definition=definition,
        child_run_id="child_run_789",
        parent_execution=parent_execution,
        parent_metadata=parent_meta,
    )

    assert len(messages) == 1
    content = messages[0]["content"]
    assert "Check pull request #42 for potential race conditions." in content
    assert "Bullet list of identified concurrency issues." in content
    assert "- **pr_number**: 42" in content
    assert "- **repo**: bytebuddhi" in content

    assert "user_id" not in metadata
    assert "project_id" not in metadata
    assert "conversation_id" not in metadata
    assert metadata["agent_id"] == "reviewer"
    assert metadata["task_id"] == "task_audit_1"
    assert "approved_actions" not in metadata
    assert "approval_granted" not in metadata
    assert "raw_secret" not in metadata


def test_context_projector_requires_execution_context():
    projector = AgentContextProjector()
    definition = AgentDefinition(
        id="coder",
        name="Coder",
        description="Writes code",
        role=AgentRole.CODER,
        system_prompt="Write code.",
    )
    task = AgentTask(task_id="t1", agent_id="coder", description="Task")
    with pytest.raises(ExecutionContextRequired):
        projector.project_child_context(
            task=task,
            definition=definition,
            child_run_id="c1",
            parent_execution=None,  # type: ignore[arg-type]
        )


def test_context_projector_excludes_secret_keys_in_input_data():
    """Verify private / security keys in input_data are omitted."""
    projector = AgentContextProjector()

    definition = AgentDefinition(
        id="coder",
        name="Coder",
        description="Writes code",
        role=AgentRole.CODER,
        system_prompt="Write code.",
    )

    task = AgentTask(
        task_id="t1",
        agent_id="coder",
        description="Task with mixed inputs",
        input_data={
            "safe_key": "safe_value",
            "approval_granted": True,
            "approved_actions": ["*"],
            "credentials": "my_secret_token",
            "secrets": "top_secret",
        },
    )

    messages, _ = projector.project_child_context(
        task=task,
        definition=definition,
        child_run_id="c1",
        parent_execution=trusted_execution_context(),
    )

    content = messages[0]["content"]
    assert "- **safe_key**: safe_value" in content
    assert "my_secret_token" not in content
    assert "top_secret" not in content
    assert "approved_actions" not in content


def test_context_projector_token_bounding():
    """Verify oversized task input is truncated safely to stay within token bounds."""
    config = MultiAgentConfig(max_child_tokens=500)
    projector = AgentContextProjector(config=config)

    definition = AgentDefinition(
        id="analyst",
        name="Analyst",
        description="Analyzes data",
        role=AgentRole.GENERALIST,
        system_prompt="Analyze.",
        token_budget=200,
    )

    task = AgentTask(
        task_id="t_huge",
        agent_id="analyst",
        description="A" * 5000,
    )

    messages, _ = projector.project_child_context(
        task=task,
        definition=definition,
        child_run_id="c_huge",
        parent_execution=trusted_execution_context(),
    )

    content = messages[0]["content"]
    assert len(content) < 1500
    assert "[Context truncated to adhere to child token budget]" in content
