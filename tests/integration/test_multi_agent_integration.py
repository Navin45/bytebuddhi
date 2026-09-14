"""End-to-end integration test for multi-agent runtime.

Exercises a compound workflow:
Parent Task
  ↓
MultiAgentOrchestrator
  ├── Task 1: Researcher inspects repository structure & symbols
  ├── Task 2: Coder writes implementation code into workspace (depends on Task 1)
  └── Task 3: Reviewer audits the written code for quality and correctness (depends on Task 2)
  ↓
Deterministic Aggregated Outcome
"""

from unittest.mock import AsyncMock

import pytest

from app.application.agent.orchestrator import MultiAgentOrchestrator
from app.application.agent.registry import create_default_registry
from app.application.agent.runtime import AgentRuntime
from app.application.policy.tool_policy import ToolPolicyEngine
from app.application.ports.output.llm.model_gateway import ModelGateway, ModelResponse
from app.application.tools.builtin.filesystem_tools import create_filesystem_tools
from app.application.tools.definition import ToolCall
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry
from app.domain.models.agent import AgentTask, TaskExecutionStatus
from app.domain.models.workspace import Workspace
from app.infrastructure.storage.local_artifact_store import LocalArtifactStore
from tests.helpers.execution import trusted_execution_context


@pytest.mark.asyncio
async def test_multi_agent_end_to_end_workflow(tmp_path):
    """Verify compound multi-agent execution with Researcher -> Coder -> Reviewer dependency chain."""
    workspace = Workspace.create(root_path=tmp_path, workspace_id="ws_multi_agent")
    artifact_store = LocalArtifactStore(base_dir=tmp_path / "artifacts")

    # 1. Setup shared ToolRegistry with native tools
    parent_registry = ToolRegistry()
    for defn, handler in create_filesystem_tools():
        parent_registry.register(defn, handler)

    policy = ToolPolicyEngine(registry=parent_registry)
    executor = ToolExecutor(
        parent_registry,
        policy_engine=policy,
        artifact_store=artifact_store,
    )

    # 2. Mock ModelGateway: delivers specialist answers based on task prompt
    mock_gateway = AsyncMock(spec=ModelGateway)

    async def model_turn_generator(messages, **kwargs):
        content_str = str(messages)
        if "Research Specialist" in content_str:
            # Researcher performs read inspection and produces research summary
            return ModelResponse(
                content="Research findings: Repository contains user authentication in auth.py. No rate limiting found.",
                tool_calls=[],
                model="test-model",
            )
        elif "Coding Specialist" in content_str:
            if (
                "call_write_fix" in content_str
                or "Successfully wrote" in content_str
                or any(m.get("role") == "tool" for m in messages if isinstance(m, dict))
            ):
                return ModelResponse(
                    content="Successfully implemented rate limiter in auth_fix.py.",
                    tool_calls=[],
                    model="test-model",
                )
            # Coder creates auth_fix.py using write_file tool
            return ModelResponse(
                content="Implemented rate limiter for auth.",
                tool_calls=[
                    ToolCall(
                        id="call_write_fix",
                        name="write_file",
                        arguments={
                            "path": "auth_fix.py",
                            "content": "# Rate limiting implementation\ndef check_rate_limit(user):\n    return True\n",
                        },
                    )
                ],
                model="test-model",
            )
        elif "Review Specialist" in content_str:
            # Reviewer inspects code and reports clean status
            return ModelResponse(
                content="Audit complete: auth_fix.py implements check_rate_limit correctly. No vulnerabilities found.",
                tool_calls=[],
                model="test-model",
            )
        return ModelResponse(content="Completed task.", tool_calls=[], model="test-model")

    mock_gateway.generate.side_effect = model_turn_generator

    # 3. Instantiate AgentRuntime & Orchestrator
    runtime = AgentRuntime(
        model_gateway=mock_gateway,
        tool_registry=parent_registry,
        tool_executor=executor,
        workspace=workspace,
    )
    agent_registry = create_default_registry()

    orchestrator = MultiAgentOrchestrator(
        agent_runtime=runtime,
        agent_registry=agent_registry,
        artifact_store=artifact_store,
        policy_engine=policy,
    )

    # 4. Define compound tasks with dependency chain: t1 (research) -> t2 (coder) -> t3 (reviewer)
    tasks = [
        AgentTask(
            task_id="t1_research",
            agent_id="researcher",
            description="Inspect authentication structure and report gaps.",
            expected_output="Summary of auth vulnerabilities",
        ),
        AgentTask(
            task_id="t2_code",
            agent_id="coder",
            description="Implement rate limiter fix in auth_fix.py based on research findings.",
            depends_on=["t1_research"],
        ),
        AgentTask(
            task_id="t3_review",
            agent_id="reviewer",
            description="Review auth_fix.py for security and correctness.",
            depends_on=["t2_code"],
        ),
    ]

    # 5. Execute orchestration
    orch_result = await orchestrator.execute_tasks(
        tasks=tasks,
        parent_context=trusted_execution_context(
            user_id="alice",
            project_id="proj_prod",
            run_id="parent_run_100",
            workspace_id=workspace.workspace_id,
        ),
    )

    # 6. Verify overall and individual status
    assert orch_result.status == TaskExecutionStatus.SUCCESS
    assert len(orch_result.child_results) == 3

    res1 = orch_result.child_results["t1_research"]
    assert res1.status == TaskExecutionStatus.SUCCESS
    assert "Research findings" in res1.answer

    res2 = orch_result.child_results["t2_code"]
    assert res2.status == TaskExecutionStatus.SUCCESS
    assert res2.tool_usage.get("write_file") == 1
    # Verify file was actually written to workspace
    assert (tmp_path / "auth_fix.py").exists()
    assert "check_rate_limit" in (tmp_path / "auth_fix.py").read_text()

    res3 = orch_result.child_results["t3_review"]
    assert res3.status == TaskExecutionStatus.SUCCESS
    assert "Audit complete" in res3.answer

    # 7. Verify aggregated outcome
    assert "Subtask [t1_research]" in orch_result.aggregated_summary
    assert "Subtask [t2_code]" in orch_result.aggregated_summary
    assert "Subtask [t3_review]" in orch_result.aggregated_summary
    assert orch_result.total_token_usage.total_tokens > 0
