"""End-to-end integration test for Phase 7 Observability across the full runtime hierarchy.

Validates that running a compound agent workflow:
1. Emits root orchestration and child run spans.
2. Preserves trace_id propagation down through child agent runs and tool execution.
3. Records metrics for orchestrations, agent runs, and tool calls.
4. Redacts secrets and isolates privacy boundaries across all spans and metric attributes.
"""

from unittest.mock import AsyncMock

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

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
from app.domain.models.observability import MetricNames, SpanAttributes, SpanNames
from app.domain.models.workspace import Workspace
from app.infrastructure.observability.otel_meter import OpenTelemetryMeter
from app.infrastructure.observability.otel_tracer import OpenTelemetryTracer
from app.infrastructure.storage.local_artifact_store import LocalArtifactStore
from tests.helpers.execution import trusted_execution_context


@pytest.mark.asyncio
async def test_full_observability_pipeline_integration(tmp_path):
    """Verify trace hierarchy and metrics during multi-agent compound execution."""
    # 1. Setup in-memory telemetry exporters
    span_exporter = InMemorySpanExporter()
    trace_provider = TracerProvider()
    trace_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    tracer = OpenTelemetryTracer(trace_provider.get_tracer("test-bytebuddhi"))

    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    meter = OpenTelemetryMeter(meter_provider.get_meter("test-bytebuddhi"))

    workspace = Workspace.create(root_path=tmp_path, workspace_id="ws_observability")
    artifact_store = LocalArtifactStore(base_dir=tmp_path / "artifacts", tracer=tracer)

    # 2. Setup ToolRegistry and PolicyEngine with telemetry
    parent_registry = ToolRegistry()
    for defn, handler in create_filesystem_tools():
        parent_registry.register(defn, handler)

    policy = ToolPolicyEngine(registry=parent_registry, tracer=tracer, meter=meter)
    executor = ToolExecutor(
        parent_registry,
        policy_engine=policy,
        artifact_store=artifact_store,
        tracer=tracer,
        meter=meter,
    )

    # 3. Setup mock LLM that invokes a tool
    mock_gateway = AsyncMock(spec=ModelGateway)

    async def model_turn_generator(messages, **kwargs):
        content_str = str(messages)
        if "Research Specialist" in content_str:
            return ModelResponse(
                content="Research findings: Checked repository.",
                tool_calls=[],
                model="test-model",
            )
        elif "Coding Specialist" in content_str:
            if any(m.get("role") == "tool" for m in messages if isinstance(m, dict)):
                return ModelResponse(
                    content="Successfully wrote implementation.",
                    tool_calls=[],
                    model="test-model",
                )
            return ModelResponse(
                content="Writing code now.",
                tool_calls=[
                    ToolCall(
                        id="call_write_test",
                        name="write_file",
                        arguments={
                            "path": "test_output.txt",
                            "content": "hello world observed",
                        },
                    )
                ],
                model="test-model",
            )
        return ModelResponse(content="Done", tool_calls=[], model="test-model")

    mock_gateway.generate.side_effect = model_turn_generator

    # 4. Setup AgentRuntime with telemetry
    runtime = AgentRuntime(
        model_gateway=mock_gateway,
        tool_registry=parent_registry,
        tool_executor=executor,
        workspace=workspace,
        tracer=tracer,
        meter=meter,
    )

    # 5. Setup MultiAgentOrchestrator with telemetry
    orchestrator = MultiAgentOrchestrator(
        agent_runtime=runtime,
        agent_registry=create_default_registry(),
        artifact_store=artifact_store,
        policy_engine=policy,
        tracer=tracer,
        meter=meter,
    )

    # 6. Execute compound multi-agent task
    tasks = [
        AgentTask(
            task_id="task_research",
            agent_id="researcher",
            description="Research Specialist: Inspect repo.",
        ),
        AgentTask(
            task_id="task_code",
            agent_id="coder",
            description="Coding Specialist: Write implementation.",
            depends_on=["task_research"],
        ),
    ]

    result = await orchestrator.execute_tasks(
        tasks=tasks,
        parent_context=trusted_execution_context(
            user_id="alice",
            project_id="proj_obs",
            run_id="parent_obs_100",
            workspace_id=workspace.workspace_id,
        ),
    )

    assert result.status == TaskExecutionStatus.SUCCESS
    assert (tmp_path / "test_output.txt").exists()

    # 7. Assert Spans
    spans = span_exporter.get_finished_spans()
    span_names = [s.name for s in spans]

    # Required span hierarchy must exist
    assert SpanNames.AGENT_ORCHESTRATION in span_names
    assert SpanNames.AGENT_CHILD_RUN in span_names
    assert SpanNames.AGENT_RUN in span_names
    assert SpanNames.TOOL_EXECUTE in span_names
    assert SpanNames.TOOL_POLICY in span_names

    # Check root trace_id consistency
    orch_span = next(s for s in spans if s.name == SpanNames.AGENT_ORCHESTRATION)
    child_spans = [s for s in spans if s.name == SpanNames.AGENT_CHILD_RUN]
    assert len(child_spans) == 2

    # All spans must share the same trace_id
    trace_id = orch_span.context.trace_id
    for s in spans:
        assert s.context.trace_id == trace_id

    # Check attributes
    tool_spans = [s for s in spans if s.name == SpanNames.TOOL_EXECUTE]
    assert len(tool_spans) >= 1
    for ts in tool_spans:
        assert SpanAttributes.TOOL_NAME in ts.attributes
        # Secrets/raw content must never leak
        assert "hello world observed" not in str(ts.attributes)

    # 8. Assert Metrics
    metric_data = metric_reader.get_metrics_data()
    assert metric_data is not None
    recorded_metric_names = [
        m.name for rm in metric_data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics
    ]

    assert MetricNames.ORCHESTRATIONS_TOTAL in recorded_metric_names
    assert MetricNames.CHILD_AGENT_RUNS_TOTAL in recorded_metric_names
    assert MetricNames.AGENT_RUNS_TOTAL in recorded_metric_names
    assert MetricNames.TOOL_CALLS_TOTAL in recorded_metric_names
    assert MetricNames.TOOL_DURATION in recorded_metric_names
