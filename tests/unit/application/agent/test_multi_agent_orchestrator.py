"""Unit tests for MultiAgentOrchestrator."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.application.agent.orchestrator import MultiAgentOrchestrator
from app.application.agent.registry import AgentRegistry
from app.application.agent.runtime import AgentRuntime
from app.application.ports.output.llm.model_gateway import ModelGateway, ModelResponse
from app.application.tools.registry import ToolRegistry
from app.domain.models.agent import (
    AgentDefinition,
    AgentRole,
    AgentTask,
    MultiAgentConfig,
    TaskExecutionStatus,
)
from app.infrastructure.storage.local_artifact_store import LocalArtifactStore
from tests.helpers.execution import trusted_execution_context


def create_test_runtime(gateway: ModelGateway, registry: ToolRegistry | None = None) -> AgentRuntime:
    return AgentRuntime(
        model_gateway=gateway,
        tool_registry=registry or ToolRegistry(),
    )


@pytest.mark.asyncio
async def test_execute_single_task_success():
    """Verify single child task executes successfully and returns structured AgentResult."""
    mock_gateway = AsyncMock(spec=ModelGateway)
    mock_gateway.generate.return_value = ModelResponse(
        content="Research completed: Found 3 relevant symbols.",
        tool_calls=[],
        model="test-model",
    )

    runtime = create_test_runtime(mock_gateway)
    registry = AgentRegistry()
    registry.register(
        AgentDefinition(
            id="researcher",
            name="Researcher",
            description="Searches code",
            role=AgentRole.RESEARCHER,
            system_prompt="Research code.",
        )
    )

    orchestrator = MultiAgentOrchestrator(
        agent_runtime=runtime,
        agent_registry=registry,
    )

    task = AgentTask(
        task_id="task_res_1",
        agent_id="researcher",
        description="Find symbol definitions for AgentRuntime.",
    )

    result = await orchestrator.execute_task(
        task, parent_context=trusted_execution_context(user_id="alice", run_id="p_run_1")
    )

    assert result.status == TaskExecutionStatus.SUCCESS
    assert result.task_id == "task_res_1"
    assert result.agent_id == "researcher"
    assert result.parent_run_id == "p_run_1"
    assert result.child_run_id.startswith("child_researcher_")
    assert "Found 3 relevant symbols" in result.answer
    assert result.error is None
    assert orchestrator.consumed_tokens > 0
    assert orchestrator.active_reservations == 0


@pytest.mark.asyncio
async def test_execute_single_task_timeout():
    """Verify child task times out gracefully when exceeding timeout_seconds."""
    mock_gateway = AsyncMock(spec=ModelGateway)

    async def slow_generate(*args, **kwargs):
        await asyncio.sleep(0.5)
        return ModelResponse(content="Done late", tool_calls=[])

    mock_gateway.generate.side_effect = slow_generate

    runtime = create_test_runtime(mock_gateway)
    registry = AgentRegistry()
    registry.register(
        AgentDefinition(
            id="tester",
            name="Tester",
            description="Runs tests",
            role=AgentRole.TESTER,
            system_prompt="Run tests.",
        )
    )

    orchestrator = MultiAgentOrchestrator(
        agent_runtime=runtime,
        agent_registry=registry,
    )

    task = AgentTask(
        task_id="task_timeout",
        agent_id="tester",
        description="Run slow tests",
        timeout_seconds=0.05,  # Very short timeout
    )

    result = await orchestrator.execute_task(task, parent_context=trusted_execution_context())
    assert result.status == TaskExecutionStatus.TIMEOUT
    assert "timed out" in result.error.lower()
    assert orchestrator.active_reservations == 0


@pytest.mark.asyncio
async def test_execute_single_task_pre_cancellation():
    """Verify child task observes cancellation before start."""
    mock_gateway = AsyncMock(spec=ModelGateway)
    runtime = create_test_runtime(mock_gateway)
    registry = AgentRegistry()
    registry.register(
        AgentDefinition(
            id="coder",
            name="Coder",
            description="Codes",
            role=AgentRole.CODER,
            system_prompt="Code.",
        )
    )

    orchestrator = MultiAgentOrchestrator(agent_runtime=runtime, agent_registry=registry)

    cancel_evt = asyncio.Event()
    cancel_evt.set()  # Cancelled beforehand

    task = AgentTask(task_id="task_cancel", agent_id="coder", description="Write code")
    result = await orchestrator.execute_task(
        task, parent_context=trusted_execution_context(), cancellation_token=cancel_evt
    )

    assert result.status == TaskExecutionStatus.CANCELLED
    assert mock_gateway.generate.call_count == 0


@pytest.mark.asyncio
async def test_atomic_global_budget_exhaustion():
    """Verify task is rejected with BUDGET_EXHAUSTED when global token budget is exceeded."""
    mock_gateway = AsyncMock(spec=ModelGateway)
    runtime = create_test_runtime(mock_gateway)
    registry = AgentRegistry()
    registry.register(
        AgentDefinition(
            id="coder",
            name="Coder",
            description="Codes",
            role=AgentRole.CODER,
            system_prompt="Code.",
        )
    )

    # Config with tiny global budget
    tiny_config = MultiAgentConfig(max_global_tokens=100, max_child_tokens=50)
    orchestrator = MultiAgentOrchestrator(
        agent_runtime=runtime,
        agent_registry=registry,
        config=tiny_config,
    )

    # Manually consume entire budget
    await orchestrator._reserve_budget(100)

    task = AgentTask(task_id="task_budget", agent_id="coder", description="Task exceeding budget")
    result = await orchestrator.execute_task(task, parent_context=trusted_execution_context())

    assert result.status == TaskExecutionStatus.BUDGET_EXHAUSTED
    assert "budget exhausted" in result.error.lower()


def test_dependency_graph_validation():
    """Verify cycle, missing dependency, duplicate ID, and valid topological ordering."""
    orchestrator = MultiAgentOrchestrator(agent_runtime=AsyncMock(), agent_registry=AgentRegistry())

    # 1. Valid DAG
    tasks_valid = [
        AgentTask(task_id="t1", agent_id="researcher", description="1"),
        AgentTask(task_id="t2", agent_id="coder", description="2", depends_on=["t1"]),
        AgentTask(task_id="t3", agent_id="reviewer", description="3", depends_on=["t2"]),
    ]
    order = orchestrator.validate_dependency_graph(tasks_valid)
    assert order == ["t1", "t2", "t3"]

    # 2. Duplicate ID
    tasks_dup = [
        AgentTask(task_id="t1", agent_id="researcher", description="1"),
        AgentTask(task_id="t1", agent_id="coder", description="duplicate"),
    ]
    with pytest.raises(ValueError, match="Duplicate task_id"):
        orchestrator.validate_dependency_graph(tasks_dup)

    # 3. Self dependency
    tasks_self = [AgentTask(task_id="t1", agent_id="researcher", description="1", depends_on=["t1"])]
    with pytest.raises(ValueError, match="Self-dependency detected"):
        orchestrator.validate_dependency_graph(tasks_self)

    # 4. Missing dependency
    tasks_missing = [AgentTask(task_id="t1", agent_id="researcher", description="1", depends_on=["t_non_existent"])]
    with pytest.raises(ValueError, match="depends on non-existent task"):
        orchestrator.validate_dependency_graph(tasks_missing)

    # 5. Circular dependency
    tasks_cycle = [
        AgentTask(task_id="t1", agent_id="researcher", description="1", depends_on=["t2"]),
        AgentTask(task_id="t2", agent_id="coder", description="2", depends_on=["t1"]),
    ]
    with pytest.raises(ValueError, match="Circular dependency detected"):
        orchestrator.validate_dependency_graph(tasks_cycle)


@pytest.mark.asyncio
async def test_execute_tasks_dependency_failure_isolation():
    """Verify when a task fails, dependent tasks are SKIPPED while independent tasks succeed."""
    mock_gateway = AsyncMock(spec=ModelGateway)

    async def generate_response(messages, **kwargs):
        # Fail task 1 intentionally
        if "Task 1 Failing" in str(messages):
            raise RuntimeError("Database connection crashed")
        return ModelResponse(content="Success response", tool_calls=[])

    mock_gateway.generate.side_effect = generate_response

    runtime = create_test_runtime(mock_gateway)
    registry = AgentRegistry()
    registry.register(
        AgentDefinition(id="researcher", name="Res", description="d", role=AgentRole.RESEARCHER, system_prompt="p")
    )
    registry.register(AgentDefinition(id="coder", name="Cod", description="d", role=AgentRole.CODER, system_prompt="p"))
    registry.register(
        AgentDefinition(id="reviewer", name="Rev", description="d", role=AgentRole.REVIEWER, system_prompt="p")
    )

    orchestrator = MultiAgentOrchestrator(agent_runtime=runtime, agent_registry=registry)

    # t1 (fails, critical=False) -> t2 depends on t1 (should skip)
    # t3 is independent (should succeed)
    tasks = [
        AgentTask(task_id="t1", agent_id="researcher", description="Task 1 Failing", is_critical=False),
        AgentTask(task_id="t2", agent_id="coder", description="Task 2 Depends on 1", depends_on=["t1"]),
        AgentTask(task_id="t3", agent_id="reviewer", description="Task 3 Independent"),
    ]

    orch_result = await orchestrator.execute_tasks(tasks, parent_context=trusted_execution_context())

    assert orch_result.child_results["t1"].status == TaskExecutionStatus.FAILED
    assert orch_result.child_results["t2"].status == TaskExecutionStatus.SKIPPED
    assert "failed/cancelled dependency 't1'" in orch_result.child_results["t2"].error
    assert orch_result.child_results["t3"].status == TaskExecutionStatus.SUCCESS


@pytest.mark.asyncio
async def test_oversized_answer_archived_to_artifact_store(tmp_path):
    """Verify child agent output exceeding max_answer_chars is archived to ArtifactStore."""
    artifact_store = LocalArtifactStore(base_dir=tmp_path / "artifacts")
    huge_output = "B" * 5000  # Exceeds max_answer_chars (4000)

    mock_gateway = AsyncMock(spec=ModelGateway)
    mock_gateway.generate.return_value = ModelResponse(content=huge_output, tool_calls=[])

    runtime = create_test_runtime(mock_gateway)
    registry = AgentRegistry()
    registry.register(AgentDefinition(id="coder", name="C", description="d", role=AgentRole.CODER, system_prompt="p"))

    config = MultiAgentConfig(max_answer_chars=4000)
    orchestrator = MultiAgentOrchestrator(
        agent_runtime=runtime,
        agent_registry=registry,
        config=config,
        artifact_store=artifact_store,
    )

    task = AgentTask(task_id="task_huge", agent_id="coder", description="Generate huge output")
    parent = trusted_execution_context(project_id="proj_test")
    result = await orchestrator.execute_task(task, parent_context=parent)

    assert result.status == TaskExecutionStatus.SUCCESS
    assert len(result.answer) < 2000
    assert "Full output archived to artifact" in result.answer
    assert len(result.artifacts) == 1

    # Verify saved in artifact store
    artifact_id = result.artifacts[0]
    loaded = await artifact_store.get_artifact(artifact_id, project_id="proj_test")
    assert loaded is not None
    assert len(loaded) == 5000


@pytest.mark.asyncio
async def test_critical_failure_skips_dependents_independent_continue():
    mock_gateway = AsyncMock(spec=ModelGateway)

    async def generate_response(messages, **kwargs):
        if "Task 1 Failing" in str(messages):
            raise RuntimeError("critical boom")
        return ModelResponse(content="Success response", tool_calls=[])

    mock_gateway.generate.side_effect = generate_response
    runtime = create_test_runtime(mock_gateway)
    registry = AgentRegistry()
    registry.register(
        AgentDefinition(id="researcher", name="Res", description="d", role=AgentRole.RESEARCHER, system_prompt="p")
    )
    registry.register(AgentDefinition(id="coder", name="Cod", description="d", role=AgentRole.CODER, system_prompt="p"))
    registry.register(
        AgentDefinition(id="reviewer", name="Rev", description="d", role=AgentRole.REVIEWER, system_prompt="p")
    )
    orchestrator = MultiAgentOrchestrator(agent_runtime=runtime, agent_registry=registry)
    tasks = [
        AgentTask(task_id="t1", agent_id="researcher", description="Task 1 Failing", is_critical=True),
        AgentTask(task_id="t2", agent_id="coder", description="Task 2 Depends on 1", depends_on=["t1"]),
        AgentTask(task_id="t3", agent_id="reviewer", description="Task 3 Independent"),
    ]
    orch_result = await orchestrator.execute_tasks(tasks, parent_context=trusted_execution_context())
    assert orch_result.child_results["t1"].status == TaskExecutionStatus.FAILED
    assert orch_result.child_results["t2"].status == TaskExecutionStatus.SKIPPED
    assert orch_result.child_results["t3"].status == TaskExecutionStatus.SUCCESS
    assert orch_result.status == TaskExecutionStatus.FAILED


@pytest.mark.asyncio
async def test_orchestration_enforces_absolute_timeout():
    runtime = AsyncMock()

    async def hang(*args, **kwargs):
        await asyncio.sleep(30)
        return None

    runtime.run = hang
    registry = AgentRegistry()
    registry.register(
        AgentDefinition(id="researcher", name="Res", description="d", role=AgentRole.RESEARCHER, system_prompt="p")
    )
    orchestrator = MultiAgentOrchestrator(
        agent_runtime=runtime,
        agent_registry=registry,
        config=MultiAgentConfig(max_orchestration_time=0.2),
    )
    result = await orchestrator.execute_tasks(
        [AgentTask(task_id="slow", agent_id="researcher", description="takes forever")],
        parent_context=trusted_execution_context(),
    )
    assert result.status in {TaskExecutionStatus.TIMEOUT, TaskExecutionStatus.CANCELLED, TaskExecutionStatus.FAILED}
    assert any(
        child.status in {TaskExecutionStatus.TIMEOUT, TaskExecutionStatus.CANCELLED, TaskExecutionStatus.FAILED}
        for child in result.child_results.values()
    )
