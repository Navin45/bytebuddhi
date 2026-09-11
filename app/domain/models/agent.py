"""Domain models for Phase 6 Multi-Agent Runtime."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


@dataclass
class TokenUsage:
    """Token usage metrics for an LLM call or run."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, other: "TokenUsage") -> "TokenUsage":
        """Sum token usages."""
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


class AgentRole(StrEnum):
    """Specialized roles for multi-agent coordination."""

    RESEARCHER = "researcher"
    CODER = "coder"
    REVIEWER = "reviewer"
    TESTER = "tester"
    PLANNER = "planner"
    GENERALIST = "generalist"


class TaskExecutionStatus(StrEnum):
    """Execution status of an individual agent task or full orchestration."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
    BUDGET_EXHAUSTED = "budget_exhausted"


class AgentLifecycleEvent(StrEnum):
    """Lifecycle events emitted during multi-agent orchestration."""

    AGENT_SPAWNED = "agent_spawned"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    AGENT_CANCELLED = "agent_cancelled"
    AGENT_TIMEOUT = "agent_timeout"
    AGENT_RESULT_AVAILABLE = "agent_result_available"
    ORCHESTRATION_COMPLETED = "orchestration_completed"


@dataclass(frozen=True)
class MultiAgentConfig:
    """Authoritative single source of truth for multi-agent orchestration limits."""

    max_child_agents: int = 10
    max_concurrent_children: int = 4
    max_delegation_depth: int = 2
    max_child_iterations: int = 10
    max_child_tokens: int = 16_000
    max_global_tokens: int = 64_000
    max_orchestration_time: float = 300.0
    max_answer_chars: int = 4000
    max_summary_chars: int = 1000


@dataclass(frozen=True)
class AgentDefinition:
    """Authoritative specification of a specialized agent.

    Security Rule:
        Definitions are registered at system initialization by trusted administrators.
        Model or task payloads CANNOT alter system_prompt, allowed_capabilities,
        role, token_budget, can_delegate, or is_mutating.
    """

    id: str
    name: str
    description: str
    role: AgentRole
    system_prompt: str
    allowed_capabilities: tuple[str, ...] | None = None
    can_delegate: bool = False
    max_iterations: int = 10
    token_budget: int | None = None
    is_mutating: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.allowed_capabilities, list):
            # Normalize to immutable tuple to prevent tampering
            object.__setattr__(self, "allowed_capabilities", tuple(self.allowed_capabilities))


@dataclass
class AgentTask:
    """Work assigned to an individual child agent.

    ``is_critical`` semantics (explicit, non-cancellable-sibling model):
        - A non-SUCCESS critical task makes the overall orchestration FAILED.
        - Dependents of any failed or cancelled task are SKIPPED.
        - Independent tasks continue to completion.
        - Critical failure does not cancel in-flight independent siblings.
    """

    task_id: str
    agent_id: str
    description: str
    input_data: dict[str, Any] = field(default_factory=dict)
    expected_output: str | None = None
    depends_on: list[str] = field(default_factory=list)
    is_critical: bool = True
    timeout_seconds: float = 60.0
    max_retries: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Structured, bounded contract returned by a child agent to the parent."""

    task_id: str
    child_run_id: str
    parent_run_id: str
    agent_id: str
    status: TaskExecutionStatus
    summary: str = ""
    answer: str = ""
    artifacts: list[str] = field(default_factory=list)
    selected_memory_refs: list[str] = field(default_factory=list)
    tool_usage: dict[str, int] = field(default_factory=dict)
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_compact_summary(self) -> str:
        """Render a compact summary suitable for parent model context without bloat."""
        status_icon = "✓" if self.status == TaskExecutionStatus.SUCCESS else "✗"
        lines = [
            f"### Subtask [{self.task_id}] ({self.agent_id}) — {status_icon} {self.status.value.upper()}",
            f"**Summary**: {self.summary or 'No summary provided.'}",
        ]
        if self.answer:
            lines.append(f"**Findings/Output**:\n{self.answer}")
        if self.artifacts:
            lines.append(f"**Artifacts**: {', '.join(self.artifacts)}")
        if self.error:
            lines.append(f"**Error**: {self.error}")
        return "\n".join(lines)


@dataclass
class OrchestrationResult:
    """Aggregated outcome of multi-agent coordination."""

    orchestration_id: str
    parent_run_id: str
    status: TaskExecutionStatus
    child_results: dict[str, AgentResult] = field(default_factory=dict)
    aggregated_summary: str = ""
    total_token_usage: TokenUsage = field(default_factory=TokenUsage)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
