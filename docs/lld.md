# Low-Level Design (LLD) — ByteBuddhi Platform

> **Document Version:** 1.0.0  
> **Status:** Production-Grade Baseline  
> **Target Layers:** Domain Models, Application Ports, Infrastructure Adapters, Interfaces

---

## 1. Hexagonal Layer Structure & Module Mapping

ByteBuddhi strictly enforces dependency inversion: **dependencies only point inward toward the Domain layer**.

```text
┌────────────────────────────────────────────────────────┐
│ Interfaces (app/interfaces/api)                        │
│   Routes, Schemas, Middleware, SSE Stream Handler      │
│   └──────────────────────────┬─────────────────────────┘
│                              │ depends on
┌──────────────────────────────▼─────────────────────────┐
│ Application (app/application)                          │
│   AgentRuntime, Orchestrator, ContextEngine, Services  │
│   Ports (app/application/ports/output)                 │
│   └──────────────────────────┬─────────────────────────┘
│                              │ depends on
┌──────────────────────────────▼─────────────────────────┐
│ Domain (app/domain)                                    │
│   Entities, Value Objects, Domain Policies, Models     │
└────────────────────────────────────────────────────────┘
                               ▲
                               │ implemented by
┌──────────────────────────────┴─────────────────────────┐
│ Infrastructure (app/infrastructure)                    │
│   Persistence, LLM Gateways, MCP, Connectors, OTel SDK │
└────────────────────────────────────────────────────────┘
```

---

## 2. Domain Entities & Core Contracts

### 2.1 Multi-Agent Domain (`app/domain/models/agent.py`)

```python
class AgentRole(StrEnum):
    CODER = "coder"
    RESEARCHER = "researcher"
    REVIEWER = "reviewer"
    TESTER = "tester"
    PLANNER = "planner"


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    role: AgentRole
    description: str
    system_prompt: str
    allowed_capabilities: tuple[str, ...]
    model: str = "gpt-4-turbo-preview"
    max_iterations: int = 15
    can_delegate: bool = False


@dataclass(frozen=True)
class AgentTask:
    task_id: str
    agent_id: str
    instruction: str
    context_keys: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    expected_output: str = ""
    timeout_seconds: float = 120.0
    is_critical: bool = True


@dataclass
class AgentResult:
    task_id: str
    child_run_id: str
    parent_run_id: str
    agent_id: str
    status: TaskExecutionStatus
    output: Any = None
    error: str | None = None
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    files_changed: list[str] = field(default_factory=list)
```

### 2.2 Capability Layer Contracts (`app/application/tools/definition.py`)

```python
class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    id: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] = field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    source: CapabilitySource = CapabilitySource.NATIVE


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    source: CapabilitySource = CapabilitySource.NATIVE


@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    status: ToolExecutionStatus
    output: Any = None
    error: str | None = None
    artifact_id: str | None = None
```

### 2.3 Memory & Storage Models (`app/domain/models/memory.py`)

```python
class MemoryType(StrEnum):
    OBSERVATION = "observation"
    DECISION = "decision"
    FACT = "fact"
    PREFERENCE = "preference"


class MemoryScope(StrEnum):
    RUN = "run"
    CONVERSATION = "conversation"
    PROJECT = "project"
    USER = "user"
    GLOBAL = "global"


@dataclass
class MemoryItem:
    id: str
    scope: MemoryScope
    memory_type: MemoryType
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 1.0
    embedding: list[float] | None = None
    ttl_seconds: int | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
```

---

## 3. Subsystem Detailed Design & Algorithms

### 3.1 LangGraph State Node Inner Agent Loop

The agent loop executes as a state machine:

```text
[START] ──> (model_node) ──> [route_decision]
                                   │
                 ┌─────────────────┴─────────────────┐
                 │ has tool_calls                    │ no tool_calls
                 ▼                                   ▼
          (tools_node)                         [END / COMPLETED]
                 │
                 ▼
          (model_node)
```

1. **`model_node`**: Invokes `ContextEngine.build_context()` to compile prompt turns. Calls `ModelGateway.generate()` with registered capability schemas.
2. **`route_decision`**: Evaluates model response:
   - If `tool_calls` present and iteration limit not exceeded: transitions to `tools_node`.
   - Otherwise: sets `AgentStatus.COMPLETED` and transitions to `END`.
3. **`tools_node`**: Iterates through requested calls:
   - Evaluates `ToolPolicyEngine.check_authorization()`.
   - Executes via `ToolExecutor.execute()`.
   - If payload length > 6,000 chars: persists to `ArtifactStore` and injects reference preview.
   - Transitions back to `model_node`.

### 3.2 ContextEngine Token Budgeting Algorithm

`ContextEngine` allocates a finite token budget (e.g. 16,000 tokens) using strict priority ordering:

```text
Total Budget
  ├── 1. System Prompt (Unprunable Anchor)
  ├── 2. Core Task Instructions (Unprunable Anchor)
  ├── 3. Capability Schemas (Filtered to Allowed Tools)
  ├── 4. Tool Execution Observations (Recent Windows)
  ├── 5. Ranked Retrieved Memories (Semantic Top-K from pgvector)
  └── 6. Conversation History Turns (Chronological, pruned oldest-first)
```

- If budget is exceeded during history evaluation, earliest turns are truncated while keeping the initial system anchor intact.
- Large tool outputs are truncated with SHA-256 artifact hashes.

### 3.3 MultiAgentOrchestrator DAG Scheduling

```python
async def execute_tasks(self, tasks, parent_context, cancellation_token):
    # 1. Validate Dependency Graph (detect cycles, missing deps)
    self._validate_dependency_graph(tasks)

    # 2. Concurrency Control with Semaphore
    semaphore = asyncio.Semaphore(self.config.max_concurrent_children)

    # 3. Execution Loop
    while remaining_tasks:
        eligible = [t for t in remaining_tasks if all_deps_succeeded(t)]
        for task in eligible:
            # Atomic budget check
            if not self._reserve_budget(task.expected_tokens):
                mark_failed(task, "Budget exhausted")
                continue

            # Project minimal context (allowlist only)
            child_ctx = self.context_projector.project(parent_context, task)
            
            # Spawn worker bounded by semaphore
            async with semaphore:
                asyncio.create_task(self.execute_task(task, child_ctx))
```

### 3.4 OpenTelemetry Application Ports

```python
class Tracer(Protocol):
    def start_span(self, name: str, parent: Any = None, attributes: dict[str, Any] = None) -> Span: ...
    def start_as_current_span(
        self, name: str, parent: Any = None, attributes: dict[str, Any] = None
    ) -> Generator[Span, None, None]: ...


class Meter(Protocol):
    def create_counter(self, name: str, unit: str = "", description: str = "") -> Counter: ...
    def create_histogram(self, name: str, unit: str = "", description: str = "") -> Histogram: ...
    def create_up_down_counter(self, name: str, unit: str = "", description: str = "") -> UpDownCounter: ...
```

- Implemented by `OpenTelemetryTracer` and `OpenTelemetryMeter` in `app/infrastructure/observability/`.
- Fallbacks automatically provided by `NoOpTracer` and `NoOpMeter` on any configuration failure.

### 3.5 Web Research Orchestration

```text
query → WebSearchProvider.search
     → select/dedupe URLs (rank order)
     → UrlSafetyPolicy.assert_safe
     → WebFetcher.fetch (no automatic redirects)
     → extract HTML → optional WebRenderer fallback
     → bound chars → ArtifactStore.save_artifact(project_id=trusted)
     → ResearchResult (previews + artifact ids)
```

- Model input is only `query` and optional `max_results`.
- Identity for artifact ownership is taken from `ToolExecutionContext`, never from tool arguments.
- Errors are domain exceptions (`UnsafeUrl`, `PrivateAddressBlocked`, `FetchTimeout`, `ContentTooLarge`, `ResearchBudgetExceeded`, `ResearchCancelled`, …).

---

## 4. Concurrency & Synchronization Model

| Resource | Concurrency Strategy | Mechanism |
|---|---|---|
| **Multi-Agent Tasks** | Bounded Concurrent Execution | `asyncio.Semaphore(max_concurrent_children=4)` |
| **Global Token Budget** | Atomic Reservation | Thread-safe in-memory reservation check |
| **Cascading Cancellation** | Cooperative Signal Broadcasting | `asyncio.Event` checked at loop boundaries |
| **Working Memory (SQLite)** | Multi-reader, single-writer | SQLite WAL mode with immediate transactions |
| **Correlation Context** | Async Task Hierarchy Isolation | Python `contextvars.ContextVar` |
| **Artifact Storage** | Atomic File Writes | Direct file write with workspace path confinement |

---

## 5. Security & Isolation Guarantees

1. **Path Traversal Guard**: All tool file paths are resolved with `os.path.realpath()` and verified against `workspace.root_path`. Traversal attempts raise `SecurityError`.
2. **Trusted Approval Guard**: `ToolPolicyEngine` authorizes `requires_approval=True` or `RiskLevel.HIGH` only from immutable `ExecutionContext.approved_actions`. Metadata, tool arguments, and parent-to-child inheritance cannot grant approval.
3. **MCP Privilege Escalation Guard**: MCP server configurations cannot set `risk_level` or `requires_approval` overrides. Internal security boundaries remain authoritative.
4. **Telemetry Privacy Guard**: Regex sanitizer in `RedactionPolicy` strips API keys (`sk-...`, `ghp_...`, `ey...`), passwords, and private certificates before exporting spans.
5. **Web Research SSRF Guard**: Untrusted fetch URLs are scheme-checked, DNS/IP classified, and re-validated on every redirect. Loopback, RFC1918, link-local/metadata, and non-http(s) schemes are rejected. DNS rebinding during connect is not perfectly eliminated. See [Web Research](web_research.md).
6. **Application Authorization**: Cross-user/project access is denied in application services and repositories. Database RLS using `auth.uid()` is not used; claiming PostgreSQL-enforced per-user isolation would be false.
7. **Managed Workspace Guard**: In `WORKSPACE_MODE=managed`, resolved workspace paths must remain inside `WORKSPACE_ROOT` after canonicalization (symlink and traversal escapes denied).
8. **Execution-scoped artifacts**: Tool/command archives require trusted `ExecutionContext`. Missing context is an error, not a write to `global/`.
