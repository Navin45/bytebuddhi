"""MultiAgentOrchestrator coordinates specialized child agents reusing the single AgentRuntime."""

import asyncio
import contextlib
from collections import defaultdict, deque
from uuid import uuid4

from app.application.agent.context_projector import AgentContextProjector
from app.application.agent.registry import AgentRegistry
from app.application.agent.runtime import AgentRuntime
from app.application.agent.types import AgentStatus, TokenUsage
from app.application.policy.tool_policy import ToolPolicyEngine
from app.application.ports.output.logger import get_logger
from app.application.ports.output.observability.context import (
    CorrelationContext,
    with_correlation_context,
)
from app.application.ports.output.observability.meter import Meter
from app.application.ports.output.observability.noop import NoOpMeter, NoOpTracer
from app.application.ports.output.observability.tracer import SpanStatus, Tracer
from app.application.ports.output.storage.artifact_store import ArtifactStore
from app.application.tools.context import ToolExecutionContext
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry
from app.domain.exceptions.execution_exceptions import ExecutionContextRequired
from app.domain.models.agent import (
    AgentDefinition,
    AgentLifecycleEvent,
    AgentResult,
    AgentTask,
    MultiAgentConfig,
    OrchestrationResult,
    TaskExecutionStatus,
)
from app.domain.models.execution_context import ExecutionContext
from app.domain.models.observability import MetricNames, SpanAttributes, SpanNames

logger = get_logger(__name__)


def _require_parent_execution(
    parent_context: ToolExecutionContext | ExecutionContext | None,
) -> ExecutionContext:
    """Resolve trusted parent identity. Metadata dicts are never accepted."""
    if isinstance(parent_context, ExecutionContext):
        return parent_context
    if isinstance(parent_context, ToolExecutionContext) and parent_context.execution is not None:
        return parent_context.execution
    raise ExecutionContextRequired(
        "MultiAgentOrchestrator requires a trusted ExecutionContext; metadata identity is not accepted"
    )


class MultiAgentOrchestrator:
    """Orchestrates multi-agent workflows using a single shared AgentRuntime.

    Core Invariants:
        1. Single Runtime Reuse: Every child agent execution invokes the proven AgentRuntime loop.
        2. Atomic Budget Reservation: Global token budget is reserved atomically before execution
           and released upon task completion, preventing concurrent budget races.
        3. Scoped Capability & Policy: A child's capabilities are the strict intersection of
           the parent's registry and the agent definition's allowed_capabilities.
        4. Dependency DAG Validation: Tasks are validated for missing dependencies and cycles
           before any execution begins.
        5. Failure & Cancellation Isolation: Dependent tasks are skipped upon dependency failure;
           cancellation cascades to all active children; timeouts clean up resources.
        6. Bounded Output: Large outputs are archived to ArtifactStore rather than ballooning context.
    """

    def __init__(
        self,
        agent_runtime: AgentRuntime,
        agent_registry: AgentRegistry,
        context_projector: AgentContextProjector | None = None,
        config: MultiAgentConfig | None = None,
        artifact_store: ArtifactStore | None = None,
        policy_engine: ToolPolicyEngine | None = None,
        tracer: Tracer | None = None,
        meter: Meter | None = None,
    ) -> None:
        self.agent_runtime = agent_runtime
        self.agent_registry = agent_registry
        self.context_projector = context_projector or AgentContextProjector(config)
        self.config = config or MultiAgentConfig()
        self.artifact_store = artifact_store
        self.policy_engine = policy_engine
        self.tracer = tracer or NoOpTracer()
        self.meter = meter or NoOpMeter()

        # Telemetry instruments
        self._orchestrations_counter = self.meter.create_counter(MetricNames.ORCHESTRATIONS_TOTAL)
        self._child_runs_counter = self.meter.create_counter(MetricNames.CHILD_AGENT_RUNS_TOTAL)
        self._child_failures_counter = self.meter.create_counter(MetricNames.CHILD_AGENT_FAILURES_TOTAL)
        self._child_timeouts_counter = self.meter.create_counter(MetricNames.CHILD_AGENT_TIMEOUTS_TOTAL)
        self._child_cancellations_counter = self.meter.create_counter(MetricNames.CHILD_AGENT_CANCELLATIONS_TOTAL)
        self._active_children_gauge = self.meter.create_up_down_counter(MetricNames.ACTIVE_CHILD_AGENTS)

        # Concurrency & Budget Locks
        self._lock = asyncio.Lock()
        self._active_token_reservations: int = 0
        self._consumed_tokens: int = 0
        self._total_delegations_count: int = 0
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_children)

    @property
    def consumed_tokens(self) -> int:
        """Total tokens consumed across all orchestrated child runs."""
        return self._consumed_tokens

    @property
    def active_reservations(self) -> int:
        """Currently reserved token allocations."""
        return self._active_token_reservations

    async def _reserve_budget(self, requested: int) -> int | None:
        """Atomically reserve a token allocation from the global budget."""
        async with self._lock:
            available = self.config.max_global_tokens - (self._consumed_tokens + self._active_token_reservations)
            if available <= 0:
                logger.warning(
                    "Global token budget exhausted",
                    consumed=self._consumed_tokens,
                    reserved=self._active_token_reservations,
                    limit=self.config.max_global_tokens,
                )
                return None
            reserved = min(requested, available)
            self._active_token_reservations += reserved
            return reserved

    async def _release_budget(self, reserved: int, actual_consumed: int) -> None:
        """Release an active reservation and record actual token consumption."""
        async with self._lock:
            self._active_token_reservations = max(0, self._active_token_reservations - reserved)
            self._consumed_tokens += actual_consumed

    def _get_scoped_tools(self, definition: AgentDefinition) -> tuple[ToolRegistry, ToolExecutor]:
        """Produce a capability registry and executor restricted to the agent definition."""
        parent_registry = self.agent_runtime.tool_registry
        if definition.allowed_capabilities is None:
            return parent_registry, self.agent_runtime.tool_executor

        scoped_registry = ToolRegistry()
        for allowed_name in definition.allowed_capabilities:
            tool_entry = parent_registry.get(allowed_name)
            if tool_entry:
                defn, handler = tool_entry
                scoped_registry.register(defn, handler)
            else:
                logger.debug(
                    "Capability not present in parent registry",
                    agent_id=definition.id,
                    capability=allowed_name,
                )

        scoped_policy = ToolPolicyEngine(
            command_policy=getattr(self.policy_engine, "command_policy", None),
            registry=scoped_registry,
            tracer=self.tracer,
            meter=self.meter,
        )
        scoped_executor = ToolExecutor(
            registry=scoped_registry,
            policy_engine=scoped_policy,
            artifact_store=self.artifact_store,
            max_output_chars=getattr(self.agent_runtime.tool_executor, "max_output_chars", 6000),
            tracer=self.tracer,
            meter=self.meter,
        )
        return scoped_registry, scoped_executor

    async def execute_task(
        self,
        task: AgentTask,
        parent_context: ToolExecutionContext | ExecutionContext | None = None,
        cancellation_token: asyncio.Event | None = None,
    ) -> AgentResult:
        """Execute a single child agent task with budget reservation, scoping, and timeout."""
        parent_execution = _require_parent_execution(parent_context)
        if isinstance(parent_context, ToolExecutionContext):
            parent_meta = dict(parent_context.metadata)
            if parent_context.cancellation_token and not cancellation_token:
                cancellation_token = parent_context.cancellation_token
        else:
            parent_meta = {}

        child_run_id = f"child_{task.agent_id}_{uuid4().hex[:8]}"
        parent_run_id = parent_execution.run_id
        parent_depth = parent_execution.delegation_depth
        child_execution = parent_execution.derive_child(child_run_id)

        # 2. Check cancellation
        if cancellation_token and cancellation_token.is_set():
            logger.info("Child task cancelled before execution start", task_id=task.task_id)
            return AgentResult(
                task_id=task.task_id,
                child_run_id=child_run_id,
                parent_run_id=parent_run_id,
                agent_id=task.agent_id,
                status=TaskExecutionStatus.CANCELLED,
                error="Cancelled before start",
            )

        # 3. Check delegation limits
        async with self._lock:
            if self._total_delegations_count >= self.config.max_child_agents:
                return AgentResult(
                    task_id=task.task_id,
                    child_run_id=child_run_id,
                    parent_run_id=parent_run_id,
                    agent_id=task.agent_id,
                    status=TaskExecutionStatus.BUDGET_EXHAUSTED,
                    error=f"Maximum child agent delegations ({self.config.max_child_agents}) exceeded",
                )
            self._total_delegations_count += 1

        # 4. Check delegation depth & permissions
        if parent_depth >= self.config.max_delegation_depth:
            return AgentResult(
                task_id=task.task_id,
                child_run_id=child_run_id,
                parent_run_id=parent_run_id,
                agent_id=task.agent_id,
                status=TaskExecutionStatus.FAILED,
                error=f"Maximum delegation depth ({self.config.max_delegation_depth}) exceeded",
            )

        calling_agent_id = parent_meta.get("agent_id")
        if calling_agent_id:
            calling_defn = self.agent_registry.get(str(calling_agent_id))
            if calling_defn and not calling_defn.can_delegate:
                return AgentResult(
                    task_id=task.task_id,
                    child_run_id=child_run_id,
                    parent_run_id=parent_run_id,
                    agent_id=task.agent_id,
                    status=TaskExecutionStatus.FAILED,
                    error=f"Agent '{calling_agent_id}' does not have delegation permission",
                )

        # 5. Resolve trusted agent definition
        definition = self.agent_registry.get(task.agent_id)
        if not definition:
            return AgentResult(
                task_id=task.task_id,
                child_run_id=child_run_id,
                parent_run_id=parent_run_id,
                agent_id=task.agent_id,
                status=TaskExecutionStatus.FAILED,
                error=f"Agent definition '{task.agent_id}' not found in trusted registry",
            )

        # 6. Atomic budget reservation
        requested_budget = min(definition.token_budget or self.config.max_child_tokens, self.config.max_child_tokens)
        reserved_tokens = await self._reserve_budget(requested_budget)
        if reserved_tokens is None:
            return AgentResult(
                task_id=task.task_id,
                child_run_id=child_run_id,
                parent_run_id=parent_run_id,
                agent_id=task.agent_id,
                status=TaskExecutionStatus.BUDGET_EXHAUSTED,
                error="Global token budget exhausted",
            )

        # 7. Project context & build scoped tools
        child_messages, child_metadata = self.context_projector.project_child_context(
            task=task,
            definition=definition,
            child_run_id=child_run_id,
            parent_execution=parent_execution,
            parent_metadata=parent_meta,
        )
        scoped_registry, scoped_executor = self._get_scoped_tools(definition)

        # 8. Execute within concurrency semaphore & timeout under child span
        consumed = 0
        attempts = 0
        max_attempts = 1 + (task.max_retries if not definition.is_mutating else 0)

        parent_span = self.tracer.get_current_span()
        with self.tracer.start_as_current_span(
            SpanNames.AGENT_CHILD_RUN,
            parent=parent_span,
            attributes={
                SpanAttributes.TASK_ID: task.task_id,
                SpanAttributes.AGENT_ID: definition.id,
                SpanAttributes.AGENT_ROLE: definition.role.value,
                SpanAttributes.PARENT_RUN_ID: parent_run_id,
                SpanAttributes.CHILD_RUN_ID: child_run_id,
                SpanAttributes.DELEGATION_DEPTH: parent_depth + 1,
            },
        ) as child_span:
            child_corr_ctx = CorrelationContext(
                trace_id=child_span.trace_id,
                span_id=child_span.span_id,
                parent_run_id=parent_run_id,
                child_run_id=child_run_id,
                agent_id=definition.id,
                task_id=task.task_id,
                user_id=child_execution.user_id_str,
                project_id=child_execution.project_id_str or "",
                conversation_id=child_execution.conversation_id_str or "",
            )
            with with_correlation_context(child_corr_ctx):
                self._active_children_gauge.add(1, {"agent_role": definition.role.value})
                try:
                    while attempts < max_attempts:
                        attempts += 1
                        try:
                            async with self._semaphore:
                                # In-flight cancellation check
                                if cancellation_token and cancellation_token.is_set():
                                    await self._release_budget(reserved_tokens, consumed)
                                    self._child_cancellations_counter.add(1, {"agent_role": definition.role.value})
                                    child_span.set_attribute(
                                        SpanAttributes.EXECUTION_STATUS, TaskExecutionStatus.CANCELLED.value
                                    )
                                    child_span.set_status(SpanStatus.ERROR, description="Execution cancelled by parent")
                                    return AgentResult(
                                        task_id=task.task_id,
                                        child_run_id=child_run_id,
                                        parent_run_id=parent_run_id,
                                        agent_id=task.agent_id,
                                        status=TaskExecutionStatus.CANCELLED,
                                        error="Execution cancelled by parent",
                                    )

                                logger.info(
                                    "Starting child agent task",
                                    lifecycle_event=AgentLifecycleEvent.AGENT_STARTED.value,
                                    task_id=task.task_id,
                                    agent_id=definition.id,
                                    child_run_id=child_run_id,
                                    parent_run_id=parent_run_id,
                                )

                                run_coro = self.agent_runtime.run(
                                    messages=child_messages,
                                    system_prompt=definition.system_prompt,
                                    run_id=child_run_id,
                                    metadata=child_metadata,
                                    execution_context=child_execution,
                                    tool_registry=scoped_registry,
                                    tool_executor=scoped_executor,
                                    max_iterations=definition.max_iterations,
                                )

                                run_state = await asyncio.wait_for(run_coro, timeout=task.timeout_seconds)

                            # Process answer and bounding
                            raw_answer = run_state.final_response or ""
                            artifacts: list[str] = []

                            if len(raw_answer) > self.config.max_answer_chars:
                                if self.artifact_store:
                                    art_id = f"artifact_{child_run_id}_{task.task_id}"
                                    ref = await self.artifact_store.save_artifact(
                                        artifact_id=art_id,
                                        content=raw_answer,
                                        metadata={"agent_id": definition.id, "task_id": task.task_id},
                                        project_id=child_execution.project_id_str,
                                    )
                                    artifacts.append(ref)
                                    answer = (
                                        f"{raw_answer[:1000]}...\n\n"
                                        f"[Full output archived to artifact '{ref}'. Total length: {len(raw_answer)} chars]"
                                    )
                                else:
                                    answer = f"{raw_answer[: self.config.max_answer_chars]}... [truncated]"
                            else:
                                answer = raw_answer

                            # Calculate tool usage counts
                            tool_counts: dict[str, int] = defaultdict(int)
                            for tc in run_state.tool_calls:
                                tool_counts[tc.name] += 1

                            # Approximate token usage based on turns
                            consumed = (len(str(child_messages)) + len(raw_answer)) // 4
                            await self._release_budget(reserved_tokens, consumed)

                            status = (
                                TaskExecutionStatus.SUCCESS
                                if run_state.status == AgentStatus.COMPLETED
                                else TaskExecutionStatus.FAILED
                            )

                            summary = (
                                answer[: self.config.max_summary_chars]
                                if len(answer) > self.config.max_summary_chars
                                else answer
                            )

                            result = AgentResult(
                                task_id=task.task_id,
                                child_run_id=child_run_id,
                                parent_run_id=parent_run_id,
                                agent_id=definition.id,
                                status=status,
                                summary=summary,
                                answer=answer,
                                artifacts=artifacts,
                                tool_usage=dict(tool_counts),
                                token_usage=TokenUsage(total_tokens=consumed),
                                error=run_state.error.message if run_state.error else None,
                            )

                            child_span.set_attribute(SpanAttributes.EXECUTION_STATUS, status.value)
                            if status == TaskExecutionStatus.SUCCESS:
                                self._child_runs_counter.add(
                                    1, {"agent_role": definition.role.value, "execution_status": "success"}
                                )
                                child_span.set_status(SpanStatus.OK)
                            else:
                                self._child_failures_counter.add(1, {"agent_role": definition.role.value})
                                child_span.set_status(SpanStatus.ERROR, description=str(result.error or "Child failed"))

                            logger.info(
                                "Child agent task finished",
                                lifecycle_event=AgentLifecycleEvent.AGENT_COMPLETED.value,
                                task_id=task.task_id,
                                status=status.value,
                            )
                            return result

                        except TimeoutError:
                            logger.warning(
                                "Child task timed out",
                                lifecycle_event=AgentLifecycleEvent.AGENT_TIMEOUT.value,
                                task_id=task.task_id,
                                timeout=task.timeout_seconds,
                            )
                            if attempts >= max_attempts:
                                await self._release_budget(reserved_tokens, consumed)
                                self._child_timeouts_counter.add(1, {"agent_role": definition.role.value})
                                child_span.set_attribute(
                                    SpanAttributes.EXECUTION_STATUS, TaskExecutionStatus.TIMEOUT.value
                                )
                                child_span.set_status(
                                    SpanStatus.ERROR, description=f"Task timed out after {task.timeout_seconds}s"
                                )
                                return AgentResult(
                                    task_id=task.task_id,
                                    child_run_id=child_run_id,
                                    parent_run_id=parent_run_id,
                                    agent_id=task.agent_id,
                                    status=TaskExecutionStatus.TIMEOUT,
                                    error=f"Task timed out after {task.timeout_seconds}s",
                                )
                        except asyncio.CancelledError:
                            logger.info(
                                "Child task cancelled",
                                lifecycle_event=AgentLifecycleEvent.AGENT_CANCELLED.value,
                                task_id=task.task_id,
                            )
                            await self._release_budget(reserved_tokens, consumed)
                            self._child_cancellations_counter.add(1, {"agent_role": definition.role.value})
                            child_span.set_attribute(
                                SpanAttributes.EXECUTION_STATUS, TaskExecutionStatus.CANCELLED.value
                            )
                            child_span.set_status(SpanStatus.ERROR, description="Task cancelled by caller")
                            return AgentResult(
                                task_id=task.task_id,
                                child_run_id=child_run_id,
                                parent_run_id=parent_run_id,
                                agent_id=task.agent_id,
                                status=TaskExecutionStatus.CANCELLED,
                                error="Task cancelled by caller",
                            )
                        except Exception as e:
                            logger.error(
                                "Child task unexpected error",
                                lifecycle_event=AgentLifecycleEvent.AGENT_FAILED.value,
                                task_id=task.task_id,
                                error=str(e),
                            )
                            if attempts >= max_attempts:
                                await self._release_budget(reserved_tokens, consumed)
                                self._child_failures_counter.add(1, {"agent_role": definition.role.value})
                                child_span.set_attribute(
                                    SpanAttributes.EXECUTION_STATUS, TaskExecutionStatus.FAILED.value
                                )
                                child_span.set_status(SpanStatus.ERROR, description=str(e))
                                return AgentResult(
                                    task_id=task.task_id,
                                    child_run_id=child_run_id,
                                    parent_run_id=parent_run_id,
                                    agent_id=task.agent_id,
                                    status=TaskExecutionStatus.FAILED,
                                    error=str(e),
                                )

                    await self._release_budget(reserved_tokens, consumed)
                    child_span.set_attribute(SpanAttributes.EXECUTION_STATUS, TaskExecutionStatus.FAILED.value)
                    child_span.set_status(SpanStatus.ERROR, description="Maximum execution retries exhausted")
                    return AgentResult(
                        task_id=task.task_id,
                        child_run_id=child_run_id,
                        parent_run_id=parent_run_id,
                        agent_id=task.agent_id,
                        status=TaskExecutionStatus.FAILED,
                        error="Maximum execution retries exhausted",
                    )
                finally:
                    self._active_children_gauge.add(-1, {"agent_role": definition.role.value})

    def validate_dependency_graph(self, tasks: list[AgentTask]) -> list[str]:
        """Validate the task dependency graph for cycles, self-dependencies, and missing dependencies.

        Returns:
            list[str]: Deterministic topological ordering of task IDs.

        Raises:
            ValueError: If graph is invalid or contains cycles.
        """
        task_ids = [t.task_id for t in tasks]
        if len(set(task_ids)) != len(tasks):
            raise ValueError("Duplicate task_id detected in tasks list")

        task_id_set = set(task_ids)
        in_degree: dict[str, int] = {t.task_id: 0 for t in tasks}
        adj_list: dict[str, list[str]] = {t.task_id: [] for t in tasks}

        for t in tasks:
            for dep in t.depends_on:
                if dep == t.task_id:
                    raise ValueError(f"Self-dependency detected for task '{t.task_id}'")
                if dep not in task_id_set:
                    raise ValueError(f"Task '{t.task_id}' depends on non-existent task '{dep}'")
                adj_list[dep].append(t.task_id)
                in_degree[t.task_id] += 1

        # Kahn's algorithm for topological sorting and cycle detection
        queue = deque([tid for tid, deg in in_degree.items() if deg == 0])
        ordered: list[str] = []

        while queue:
            curr = queue.popleft()
            ordered.append(curr)
            for neighbor in adj_list[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(ordered) != len(tasks):
            raise ValueError("Circular dependency detected in tasks graph")

        return ordered

    async def execute_tasks(
        self,
        tasks: list[AgentTask],
        parent_context: ToolExecutionContext | ExecutionContext | None = None,
        cancellation_token: asyncio.Event | None = None,
    ) -> OrchestrationResult:
        """Execute a graph of tasks with topological dependency order and concurrency bounds."""
        orchestration_id = f"orch_{uuid4().hex[:8]}"
        parent_execution = _require_parent_execution(parent_context)
        parent_run_id = parent_execution.run_id
        if (
            isinstance(parent_context, ToolExecutionContext)
            and parent_context.cancellation_token
            and not cancellation_token
        ):
            cancellation_token = parent_context.cancellation_token

        if not tasks:
            return OrchestrationResult(
                orchestration_id=orchestration_id,
                parent_run_id=parent_run_id,
                status=TaskExecutionStatus.SUCCESS,
                child_results={},
                aggregated_summary="No tasks specified.",
            )

        # 1. Validate DAG before beginning any execution
        self.validate_dependency_graph(tasks)

        parent_span = self.tracer.get_current_span()
        with self.tracer.start_as_current_span(
            SpanNames.AGENT_ORCHESTRATION,
            parent=parent_span,
            attributes={
                SpanAttributes.ORCHESTRATION_ID: orchestration_id,
                SpanAttributes.PARENT_RUN_ID: parent_run_id,
                "bytebuddhi.tasks_count": len(tasks),
            },
        ) as orch_span:
            self._orchestrations_counter.add(1)

            tasks_by_id = {t.task_id: t for t in tasks}
            results: dict[str, AgentResult] = {}
            running_tasks: dict[str, asyncio.Task[AgentResult]] = {}
            total_tokens = TokenUsage()
            aborted = False

            try:
                while len(results) < len(tasks):
                    # Check overall cancellation
                    if cancellation_token and cancellation_token.is_set():
                        logger.info(
                            "Orchestration cancelled, stopping remaining tasks", orchestration_id=orchestration_id
                        )
                        for tid, t in tasks_by_id.items():
                            if tid not in results and tid not in running_tasks:
                                results[tid] = AgentResult(
                                    task_id=tid,
                                    child_run_id="",
                                    parent_run_id=parent_run_id,
                                    agent_id=t.agent_id,
                                    status=TaskExecutionStatus.CANCELLED,
                                    error="Cancelled by parent",
                                )
                        break

                    # Find eligible tasks
                    for tid, task in tasks_by_id.items():
                        if tid in results or tid in running_tasks:
                            continue

                        # Check dependencies
                        deps_satisfied = True
                        dep_failed = False
                        failing_dep_name = None

                        for dep in task.depends_on:
                            if dep not in results:
                                deps_satisfied = False
                                break
                            if results[dep].status != TaskExecutionStatus.SUCCESS:
                                dep_failed = True
                                failing_dep_name = dep
                                break

                        if dep_failed or aborted:
                            reason = (
                                f"Skipped due to failed/cancelled dependency '{failing_dep_name}'"
                                if dep_failed
                                else "Skipped due to prior critical task failure"
                            )
                            results[tid] = AgentResult(
                                task_id=tid,
                                child_run_id="",
                                parent_run_id=parent_run_id,
                                agent_id=task.agent_id,
                                status=TaskExecutionStatus.SKIPPED,
                                error=reason,
                            )
                            continue

                        if deps_satisfied:
                            task_handle = asyncio.create_task(
                                self.execute_task(
                                    task=task,
                                    parent_context=parent_context,
                                    cancellation_token=cancellation_token,
                                )
                            )
                            running_tasks[tid] = task_handle

                    if not running_tasks:
                        break

                    done, _ = await asyncio.wait(
                        running_tasks.values(),
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    for done_task in done:
                        completed_tid = next(tid for tid, handle in running_tasks.items() if handle == done_task)
                        running_tasks.pop(completed_tid)
                        try:
                            res = await done_task
                            results[completed_tid] = res
                            total_tokens = total_tokens.add(res.token_usage)

                            if res.status != TaskExecutionStatus.SUCCESS and tasks_by_id[completed_tid].is_critical:
                                logger.warning(
                                    "Critical child task failed, triggering dependent skip",
                                    task_id=completed_tid,
                                    status=res.status.value,
                                )
                        except Exception as exc:
                            results[completed_tid] = AgentResult(
                                task_id=completed_tid,
                                child_run_id="",
                                parent_run_id=parent_run_id,
                                agent_id=tasks_by_id[completed_tid].agent_id,
                                status=TaskExecutionStatus.FAILED,
                                error=str(exc),
                            )

            except Exception as e:
                logger.error("Error during task execution loop", orchestration_id=orchestration_id, error=str(e))
                aborted = True

            # Cancel any still-running tasks on abort/cancellation
            for handle in running_tasks.values():
                if not handle.done():
                    handle.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await handle

            ordered_results = {
                t.task_id: results.get(t.task_id)
                or AgentResult(
                    task_id=t.task_id,
                    child_run_id="",
                    parent_run_id=parent_run_id,
                    agent_id=t.agent_id,
                    status=TaskExecutionStatus.FAILED,
                    error="Task did not execute",
                )
                for t in tasks
            }

            all_success = all(r.status == TaskExecutionStatus.SUCCESS for r in ordered_results.values())
            any_cancelled = any(r.status == TaskExecutionStatus.CANCELLED for r in ordered_results.values())
            final_status = (
                TaskExecutionStatus.SUCCESS
                if all_success
                else (TaskExecutionStatus.CANCELLED if any_cancelled else TaskExecutionStatus.FAILED)
            )

            summaries = [res.to_compact_summary() for res in ordered_results.values()]
            aggregated_summary = "\n\n".join(summaries)
            errors = [r.error for r in ordered_results.values() if r.error]

            logger.info(
                "MultiAgentOrchestrator completed",
                lifecycle_event=AgentLifecycleEvent.ORCHESTRATION_COMPLETED.value,
                orchestration_id=orchestration_id,
                status=final_status.value,
                tasks_count=len(ordered_results),
            )

            orch_span.set_attribute(SpanAttributes.EXECUTION_STATUS, final_status.value)
            if final_status == TaskExecutionStatus.SUCCESS:
                orch_span.set_status(SpanStatus.OK)
            else:
                orch_span.set_status(SpanStatus.ERROR, description=f"Orchestration status: {final_status.value}")

            return OrchestrationResult(
                orchestration_id=orchestration_id,
                parent_run_id=parent_run_id,
                status=final_status,
                child_results=ordered_results,
                aggregated_summary=aggregated_summary,
                total_token_usage=total_tokens,
                errors=errors,
            )
