"""Observability domain models, controlled vocabularies, and data protection policies."""

import re
from enum import StrEnum
from typing import Any


class ExecutionTelemetryStatus(StrEnum):
    """Execution status vocabulary for telemetry reporting."""

    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class SpanNames:
    """Stable, deterministic span names."""

    AGENT_RUN = "agent.run"
    AGENT_ORCHESTRATION = "agent.orchestration"
    AGENT_CHILD_RUN = "agent.child_run"
    TOOL_EXECUTE = "tool.execute"
    TOOL_POLICY = "tool.policy"
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    MEMORY_SEARCH = "memory.search"
    ARTIFACT_STORE = "artifact.store"
    ARTIFACT_GET = "artifact.get"
    PROCESS_EXECUTE = "process.execute"
    CONNECTOR_REQUEST = "connector.request"
    MCP_EXECUTE = "mcp.execute"


class SpanAttributes:
    """Standard controlled vocabulary for span and event attributes."""

    PREFIX = "bytebuddhi."

    # Agent / Multi-Agent Identifiers
    AGENT_ID = "bytebuddhi.agent.id"
    AGENT_ROLE = "bytebuddhi.agent.role"
    TASK_ID = "bytebuddhi.task.id"
    PARENT_RUN_ID = "bytebuddhi.parent_run.id"
    CHILD_RUN_ID = "bytebuddhi.child_run.id"
    ORCHESTRATION_ID = "bytebuddhi.orchestration.id"
    USER_ID = "bytebuddhi.user.id"
    PROJECT_ID = "bytebuddhi.project.id"
    CONVERSATION_ID = "bytebuddhi.conversation.id"
    DELEGATION_DEPTH = "bytebuddhi.delegation.depth"

    # Status & Lifecycle
    EXECUTION_STATUS = "bytebuddhi.execution.status"
    LIFECYCLE_EVENT = "bytebuddhi.lifecycle_event"
    ERROR_TYPE = "bytebuddhi.error.type"
    ERROR_MESSAGE = "bytebuddhi.error.message"

    # Tool & Capability
    TOOL_ID = "bytebuddhi.tool.id"
    TOOL_NAME = "bytebuddhi.tool.name"
    TOOL_RISK = "bytebuddhi.tool.risk"
    TOOL_APPROVAL_REQUIRED = "bytebuddhi.tool.approval_required"
    TOOL_APPROVAL_STATUS = "bytebuddhi.tool.approval_status"
    POLICY_DECISION = "bytebuddhi.policy.decision"
    DENIAL_REASON = "bytebuddhi.policy.denial_reason"

    # Memory
    MEMORY_SCOPE = "bytebuddhi.memory.scope"
    MEMORY_OPERATION = "bytebuddhi.memory.operation"
    MEMORY_RESULT_COUNT = "bytebuddhi.memory.result_count"

    # Artifact
    ARTIFACT_ID = "bytebuddhi.artifact.id"
    ARTIFACT_SIZE_BYTES = "bytebuddhi.artifact.size_bytes"
    ARTIFACT_TYPE = "bytebuddhi.artifact.type"

    # Process
    PROCESS_EXIT_CODE = "bytebuddhi.process.exit_code"
    PROCESS_COMMAND_CATEGORY = "bytebuddhi.process.command_category"

    # Connectors & MCP
    CONNECTOR_TYPE = "bytebuddhi.connector.type"
    CONNECTOR_OPERATION = "bytebuddhi.connector.operation"
    HTTP_STATUS = "bytebuddhi.http.status_code"
    RETRY_COUNT = "bytebuddhi.retry.count"
    MCP_SERVER = "bytebuddhi.mcp.server"
    MCP_CAPABILITY = "bytebuddhi.mcp.capability"


class MetricNames:
    """Controlled metric names across ByteBuddhi subsystems."""

    # Agent Metrics
    AGENT_RUNS_TOTAL = "bytebuddhi.agent_runs_total"
    AGENT_RUN_FAILURES_TOTAL = "bytebuddhi.agent_run_failures_total"
    AGENT_RUN_DURATION = "bytebuddhi.agent_run_duration"
    AGENT_TOKEN_USAGE = "bytebuddhi.agent_token_usage"

    # Multi-Agent Metrics
    ORCHESTRATIONS_TOTAL = "bytebuddhi.orchestrations_total"
    CHILD_AGENT_RUNS_TOTAL = "bytebuddhi.child_agent_runs_total"
    CHILD_AGENT_FAILURES_TOTAL = "bytebuddhi.child_agent_failures_total"
    CHILD_AGENT_TIMEOUTS_TOTAL = "bytebuddhi.child_agent_timeouts_total"
    CHILD_AGENT_CANCELLATIONS_TOTAL = "bytebuddhi.child_agent_cancellations_total"
    ACTIVE_CHILD_AGENTS = "bytebuddhi.active_child_agents"

    # Tool Metrics
    TOOL_CALLS_TOTAL = "bytebuddhi.tool_calls_total"
    TOOL_FAILURES_TOTAL = "bytebuddhi.tool_failures_total"
    TOOL_DENIALS_TOTAL = "bytebuddhi.tool_denials_total"
    TOOL_DURATION = "bytebuddhi.tool_duration"

    # Process Metrics
    PROCESS_EXECUTIONS_TOTAL = "bytebuddhi.process_executions_total"
    PROCESS_FAILURES_TOTAL = "bytebuddhi.process_failures_total"
    PROCESS_DURATION = "bytebuddhi.process_duration"

    # Memory Metrics
    MEMORY_READS_TOTAL = "bytebuddhi.memory_reads_total"
    MEMORY_WRITES_TOTAL = "bytebuddhi.memory_writes_total"
    MEMORY_FAILURES_TOTAL = "bytebuddhi.memory_failures_total"
    MEMORY_OPERATION_DURATION = "bytebuddhi.memory_operation_duration"

    # Connector / MCP Metrics
    CONNECTOR_REQUESTS_TOTAL = "bytebuddhi.connector_requests_total"
    CONNECTOR_FAILURES_TOTAL = "bytebuddhi.connector_failures_total"
    CONNECTOR_DURATION = "bytebuddhi.connector_duration"
    MCP_CALLS_TOTAL = "bytebuddhi.mcp_calls_total"
    MCP_FAILURES_TOTAL = "bytebuddhi.mcp_failures_total"
    MCP_DURATION = "bytebuddhi.mcp_duration"


class RedactionPolicy:
    """Centralized sensitive data redaction policy for telemetry boundaries."""

    _SENSITIVE_KEY_PATTERN = re.compile(
        r"(?i)(authorization|api[_-]?key|token|password|secret|credential|cookie|set-cookie|private[_-]?key|access[_-]?token|refresh[_-]?token)"
    )

    _SENSITIVE_VALUE_PATTERNS = [
        re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{10,}"),
        re.compile(r"-----BEGIN[ A-Z0-9_-]+KEY-----[\s\S]+?-----END[ A-Z0-9_-]+KEY-----"),
        re.compile(r"(?i)(password|secret|key|token)\s*[:=]\s*['\"][^'\"]+['\"]"),
    ]

    REDACTED_TEXT = "[REDACTED]"

    @classmethod
    def is_sensitive_key(cls, key: str) -> bool:
        """Check if attribute or dictionary key matches sensitive patterns."""
        return bool(cls._SENSITIVE_KEY_PATTERN.search(key))

    @classmethod
    def sanitize_string(cls, value: str) -> str:
        """Mask sensitive tokens or private keys inside string values."""
        if not value:
            return value

        sanitized = value
        for pattern in cls._SENSITIVE_VALUE_PATTERNS:
            sanitized = pattern.sub(cls.REDACTED_TEXT, sanitized)
        return sanitized

    @classmethod
    def sanitize_attributes(cls, attributes: dict[str, Any]) -> dict[str, Any]:
        """Deeply sanitize an attribute dictionary before passing to tracing or logging."""
        sanitized: dict[str, Any] = {}
        for k, v in attributes.items():
            if cls.is_sensitive_key(str(k)):
                sanitized[k] = cls.REDACTED_TEXT
            elif isinstance(v, str):
                sanitized[k] = cls.sanitize_string(v)
            elif isinstance(v, dict):
                sanitized[k] = cls.sanitize_attributes(v)
            elif isinstance(v, (list, tuple)):
                sanitized[k] = [
                    cls.sanitize_attributes(item)
                    if isinstance(item, dict)
                    else cls.sanitize_string(str(item))
                    if isinstance(item, str)
                    else item
                    for item in v
                ]
            else:
                sanitized[k] = v
        return sanitized

    @classmethod
    def sanitize_exception_message(cls, message: str, max_chars: int = 300) -> str:
        """Sanitize and bound exception error messages for safe telemetry."""
        sanitized = cls.sanitize_string(message)
        if len(sanitized) > max_chars:
            return f"{sanitized[:max_chars]}... [truncated]"
        return sanitized


class DataBoundingPolicy:
    """Enforces bounding rules on telemetry payloads to prevent high-cardinality or data leakage."""

    MAX_STRING_LEN = 200

    # Whitelist of bounded dimensional labels permitted for metrics
    ALLOWED_METRIC_DIMENSIONS = {
        "agent_role",
        "tool_type",
        "tool_name",
        "risk_level",
        "execution_status",
        "operation_type",
        "provider_type",
        "status_code",
        "connector_type",
        "mcp_server",
        "memory_scope",
        "error_type",
    }

    @classmethod
    def bound_attribute_value(cls, val: Any) -> Any:
        """Ensure string values in span attributes remain safely bounded."""
        if isinstance(val, str):
            if len(val) > cls.MAX_STRING_LEN:
                return f"{val[: cls.MAX_STRING_LEN]}... [truncated]"
            return val
        return val

    @classmethod
    def sanitize_and_bound_metric_attributes(cls, attributes: dict[str, Any]) -> dict[str, str]:
        """Filter metric attributes to strictly bounded cardinality dimensions."""
        bounded: dict[str, str] = {}
        for k, v in attributes.items():
            clean_key = str(k).lower().replace("bytebuddhi.", "").replace(".", "_")
            if clean_key in cls.ALLOWED_METRIC_DIMENSIONS:
                val_str = str(v)
                if not RedactionPolicy.is_sensitive_key(clean_key):
                    bounded[clean_key] = val_str[:50]
        return bounded
