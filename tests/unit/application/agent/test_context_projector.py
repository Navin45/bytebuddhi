"""Unit tests for AgentContextProjector."""

from app.application.agent.context_projector import AgentContextProjector
from app.domain.models.agent import AgentDefinition, AgentRole, AgentTask, MultiAgentConfig


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

    parent_meta = {
        "user_id": "alice",
        "project_id": "proj_123",
        "conversation_id": "conv_456",
        "run_id": "parent_run_001",
        "delegation_depth": 0,
        # Sensitive fields that must NOT be passed to child
        "approved_actions": ["github_create_issue"],
        "approval_granted": True,
        "raw_secret": "sensitive_token",
    }

    messages, metadata = projector.project_child_context(
        task=task,
        definition=definition,
        child_run_id="child_run_789",
        parent_metadata=parent_meta,
    )

    # 1. Verify messages content
    assert len(messages) == 1
    content = messages[0]["content"]
    assert "Check pull request #42 for potential race conditions." in content
    assert "Bullet list of identified concurrency issues." in content
    assert "- **pr_number**: 42" in content
    assert "- **repo**: bytebuddhi" in content

    # 2. Verify identity fields preserved immutably
    assert metadata["user_id"] == "alice"
    assert metadata["project_id"] == "proj_123"
    assert metadata["conversation_id"] == "conv_456"
    assert metadata["parent_run_id"] == "parent_run_001"
    assert metadata["child_run_id"] == "child_run_789"
    assert metadata["delegation_depth"] == 1

    # 3. Verify security isolation: approval metadata excluded
    assert "approved_actions" not in metadata
    assert "approval_granted" not in metadata
    assert "raw_secret" not in metadata


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
        parent_metadata={},
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
        token_budget=200,  # 200 tokens ~ 800 chars
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
        parent_metadata={},
    )

    content = messages[0]["content"]
    assert len(content) < 1500
    assert "[Context truncated to adhere to child token budget]" in content
