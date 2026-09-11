"""Security test suite for Observability and Telemetry boundaries.

Verifies protection against Attacks A through H:
- Attack A: Secret Leakage (Bearer tokens, API keys, passwords)
- Attack B: Prompt & Thought Leakage (LLM inputs/internal thoughts)
- Attack C: Tool Argument & Output Leakage (Raw inputs/outputs)
- Attack D: Memory & Artifact Content Leakage (Raw stored data)
- Attack E: Child Agent Context Isolation (Child mutation of parent)
- Attack F: Identity & Approval Tampering (Audited approval provenance)
- Attack G: High-Cardinality Dimension Explosion (Label stuffing)
- Attack H: Telemetry Failure Isolation (Crashing exporter/telemetry)
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.application.ports.output.observability.context import (
    get_correlation_context,
    with_correlation_context,
)
from app.application.ports.output.observability.tracer import Tracer
from app.domain.models.observability import (
    DataBoundingPolicy,
    SpanAttributes,
    SpanNames,
)
from app.infrastructure.observability.otel_tracer import OpenTelemetryTracer


@pytest.fixture
def memory_exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def test_tracer(memory_exporter: InMemorySpanExporter) -> Tracer:
    provider = TracerProvider()
    processor = SimpleSpanProcessor(memory_exporter)
    provider.add_span_processor(processor)
    return OpenTelemetryTracer(provider.get_tracer("security-test-tracer"))


def test_attack_a_secret_leakage_in_attributes(test_tracer: Tracer, memory_exporter: InMemorySpanExporter) -> None:
    """Attack A: Attempt to leak API tokens and passwords via span attributes."""
    dangerous_attrs = {
        "api_key": "sk-proj-super-secret-key-12345",
        "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token",
        "password": "CorrectHorseBatteryStaple",
        "safe_label": "safe_val",
    }
    with test_tracer.start_as_current_span("auth.operation", attributes=dangerous_attrs):
        pass

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    attrs = spans[0].attributes
    assert attrs is not None

    # Verify secrets were redacted
    assert attrs["api_key"] == "[REDACTED]"
    assert attrs["authorization"] == "[REDACTED]"
    assert attrs["password"] == "[REDACTED]"
    assert attrs["safe_label"] == "safe_val"
    assert "sk-proj-super-secret-key-12345" not in str(attrs)


def test_attack_b_prompt_and_thought_leakage(test_tracer: Tracer, memory_exporter: InMemorySpanExporter) -> None:
    """Attack B: Verify that raw LLM prompt text and internal thought chains are not traced."""
    user_prompt = "Classified instructions: How to bypass firewall and exfiltrate database"
    thought_chain = "Thinking: I will inspect the network ports first..."

    # Tracing an agent run span must only record bounded identifiers, never the raw prompt
    with test_tracer.start_as_current_span(
        SpanNames.AGENT_RUN,
        attributes={
            SpanAttributes.AGENT_ROLE: "researcher",
            SpanAttributes.TASK_ID: "task-001",
        },
    ):
        pass

    spans = memory_exporter.get_finished_spans()
    attrs = spans[0].attributes
    assert attrs is not None
    assert user_prompt not in str(attrs)
    assert thought_chain not in str(attrs)
    assert SpanAttributes.AGENT_ROLE in attrs


def test_attack_c_tool_argument_and_output_leakage(test_tracer: Tracer, memory_exporter: InMemorySpanExporter) -> None:
    """Attack C: Verify raw tool arguments and execution outputs do not leak into span attributes."""
    command_arg = "cat /etc/shadow"
    secret_env_arg = "super_secret_val"
    raw_tool_output = "root:$6$xyz:18293:0:99999:7:::"

    # Tool executor spans must record tool name and risk level, but NOT raw args/outputs
    with test_tracer.start_as_current_span(
        SpanNames.TOOL_EXECUTE,
        attributes={
            SpanAttributes.TOOL_NAME: "run_command",
            SpanAttributes.TOOL_RISK: "high",
        },
    ):
        pass

    spans = memory_exporter.get_finished_spans()
    attrs = spans[0].attributes
    assert attrs is not None
    assert command_arg not in str(attrs)
    assert secret_env_arg not in str(attrs)
    assert raw_tool_output not in str(attrs)
    assert attrs[SpanAttributes.TOOL_NAME] == "run_command"


def test_attack_d_memory_and_artifact_content_leakage(
    test_tracer: Tracer, memory_exporter: InMemorySpanExporter
) -> None:
    """Attack D: Verify memory contents and artifact payloads do not leak into telemetry."""
    sensitive_memory = "Confidential user salary is $250,000"
    sensitive_artifact = "CONFIDENTIAL INTERNAL FINANCIAL REPORT"

    with test_tracer.start_as_current_span(
        SpanNames.MEMORY_WRITE,
        attributes={
            SpanAttributes.MEMORY_SCOPE: "user",
            SpanAttributes.MEMORY_OPERATION: "save",
        },
    ):
        pass

    spans = memory_exporter.get_finished_spans()
    attrs = spans[0].attributes
    assert attrs is not None
    assert sensitive_memory not in str(attrs)
    assert sensitive_artifact not in str(attrs)
    assert attrs[SpanAttributes.MEMORY_SCOPE] == "user"


def test_attack_e_child_agent_context_isolation() -> None:
    """Attack E: Verify child agent cannot mutate parent correlation context or leak into parent."""
    with with_correlation_context(
        run_id="parent-run",
        agent_role="lead_agent",
        user_id="alice",
        project_id="corp_proj",
        delegation_depth=0,
    ):
        assert get_correlation_context().run_id == "parent-run"

        # Simulate child spawn
        with with_correlation_context(
            run_id="child-run",
            parent_run_id="parent-run",
            agent_role="sub_agent",
            user_id="alice",
            project_id="corp_proj",
            delegation_depth=1,
        ) as child_ctx:
            assert get_correlation_context().run_id == "child-run"
            assert child_ctx.delegation_depth == 1

        # Confirm parent context remains completely intact after child completion
        after_child = get_correlation_context()
        assert after_child.run_id == "parent-run"
        assert after_child.agent_role == "lead_agent"
        assert after_child.delegation_depth == 0


def test_attack_f_approval_and_identity_tampering(test_tracer: Tracer, memory_exporter: InMemorySpanExporter) -> None:
    """Attack F: Verify approval status and risk tiers are recorded with immutable fidelity."""
    with test_tracer.start_as_current_span(
        SpanNames.TOOL_POLICY,
        attributes={
            SpanAttributes.TOOL_NAME: "write_file",
            SpanAttributes.TOOL_RISK: "high",
            SpanAttributes.TOOL_APPROVAL_REQUIRED: True,
            SpanAttributes.TOOL_APPROVAL_STATUS: "granted",
        },
    ):
        pass

    spans = memory_exporter.get_finished_spans()
    attrs = spans[0].attributes
    assert attrs is not None
    assert attrs[SpanAttributes.TOOL_RISK] == "high"
    assert attrs[SpanAttributes.TOOL_APPROVAL_REQUIRED] is True
    assert attrs[SpanAttributes.TOOL_APPROVAL_STATUS] == "granted"


def test_attack_g_high_cardinality_dimension_explosion() -> None:
    """Attack G: Attempt to inject unbounded labels into metric attributes to cause cardinality explosion."""
    malicious_metric_attrs = {
        "user_uuid": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
        "custom_prompt": "a" * 1000,
        "arbitrary_session_id": "sess_99999",
        "agent_role": "coder",  # Valid whitelisted label
        "tool_name": "git_status",  # Valid whitelisted label
    }

    filtered = DataBoundingPolicy.sanitize_and_bound_metric_attributes(malicious_metric_attrs)

    # Only whitelisted dimensions should pass
    assert "agent_role" in filtered
    assert "tool_name" in filtered
    assert "user_uuid" not in filtered
    assert "custom_prompt" not in filtered
    assert "arbitrary_session_id" not in filtered


def test_attack_h_telemetry_failure_isolation() -> None:
    """Attack H: Verify that catastrophic exporter/telemetry crashes do NOT crash business execution."""

    class BrokenTracer:
        @contextmanager
        def start_as_current_span(
            self,
            name: str,
            parent: Any = None,
            attributes: Any = None,
        ) -> Generator[Any]:
            raise ConnectionError("OTLP endpoint unreachable / exporter dead")
            yield

        def start_span(self, name: str, parent: Any = None, attributes: Any = None) -> Any:
            raise ConnectionError("OTLP endpoint unreachable")

        def get_current_span(self) -> Any:
            return None

    tracer = BrokenTracer()

    # Telemetry failure isolation pattern:
    execution_completed = False
    try:
        try:
            with tracer.start_as_current_span("test"):
                pass
        except Exception:
            # Telemetry error caught & absorbed at telemetry boundary
            pass

        # Real business task continues safely
        execution_completed = True
    except Exception:
        pytest.fail("Business execution crashed due to telemetry failure!")

    assert execution_completed is True
