"""AgentRuntime for ByteBuddhi.

Provides the inner agent execution loop orchestrated via LangGraph.
"""

import time
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.application.agent.context import ContextEngine
from app.application.agent.errors import (
    AgentError,
    IterationLimitExceededError,
    ModelCallError,
)
from app.application.agent.state import AgentLoopState, AgentRunState
from app.application.agent.types import AgentStatus
from app.application.memory.orchestrator import MemoryOrchestrator
from app.application.ports.output.llm.model_gateway import ModelGateway
from app.application.ports.output.logger import get_logger
from app.application.ports.output.observability.context import get_correlation_context
from app.application.ports.output.observability.meter import Meter
from app.application.ports.output.observability.noop import NoOpMeter, NoOpTracer
from app.application.ports.output.observability.tracer import SpanStatus, Tracer
from app.application.tools.context import ToolExecutionContext, auxiliary_metadata
from app.application.tools.definition import ToolCall
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry
from app.domain.exceptions.execution_exceptions import ExecutionContextRequired
from app.domain.models.execution_context import ExecutionContext
from app.domain.models.memory import ExecutionObservation, MemoryScope
from app.domain.models.observability import MetricNames, SpanAttributes, SpanNames
from app.domain.models.workspace import Workspace

logger = get_logger(__name__)


def create_agent_loop_graph(
    model_gateway: ModelGateway,
    tool_registry: ToolRegistry,
    tool_executor: ToolExecutor,
    context_engine: ContextEngine,
    system_prompt: str,
    checkpointer: BaseCheckpointSaver | None = None,
    workspace: Workspace | None = None,
    memory_orchestrator: MemoryOrchestrator | None = None,
    execution_context: ExecutionContext | None = None,
) -> CompiledStateGraph:
    """Build and compile the inner agent loop StateGraph using LangGraph."""

    async def model_node(state: AgentLoopState) -> dict[str, Any]:
        iteration = state.get("iteration", 0) + 1
        max_iterations = state.get("max_iterations", 10)

        # 1. Enforce iteration limits
        if iteration > max_iterations:
            logger.warning(
                "Agent iteration limit reached",
                iteration=iteration,
                max_iterations=max_iterations,
                run_id=state.get("run_id"),
            )
            err = IterationLimitExceededError(iteration, max_iterations)
            return {
                "iteration": iteration,
                "status": AgentStatus.FAILED.value,
                "error": err.to_dict(),
            }

        # 2. Retrieve relevant memories and build model context
        tool_schemas = tool_registry.get_schemas_for_openai()
        retrieved_memories = []
        if memory_orchestrator:
            if execution_context is None:
                raise ExecutionContextRequired("AgentRuntime memory retrieval requires a trusted ExecutionContext")
            run_id = execution_context.run_id
            scopes = [(MemoryScope.AGENT_RUN, run_id)]
            if execution_context.project_id_str:
                scopes.append((MemoryScope.PROJECT, execution_context.project_id_str))
            scopes.append((MemoryScope.USER, execution_context.user_id_str))

            last_query = ""
            for m in reversed(state.get("messages", [])):
                if m.get("role") == "user":
                    last_query = str(m.get("content", ""))
                    break

            try:
                retrieved_memories = await memory_orchestrator.retrieve_memories(
                    query=last_query or None,
                    scopes=scopes,
                    limit=5,
                )
            except Exception as me:
                logger.warning("Failed to retrieve memories for model context", error=str(me))

        model_context = context_engine.build_model_context(
            system_prompt=system_prompt,
            messages=state.get("messages", []),
            tool_definitions=tool_schemas if tool_schemas else None,
            memories=retrieved_memories,
        )
        messages = model_context.to_model_messages()

        # 3. Invoke ModelGateway
        try:
            response = await model_gateway.generate(
                messages=messages,
                tools=tool_schemas if tool_schemas else None,
            )
        except AgentError as ae:
            logger.error("ModelGateway error during agent loop", error=str(ae))
            return {
                "iteration": iteration,
                "status": AgentStatus.FAILED.value,
                "error": ae.to_dict(),
            }
        except Exception as e:
            logger.error("Unexpected error during agent loop model call", error=str(e))
            wrapped_err = ModelCallError(message=str(e), cause=e)
            return {
                "iteration": iteration,
                "status": AgentStatus.FAILED.value,
                "error": wrapped_err.to_dict(),
            }

        # 4. Process decision
        if response.has_tool_calls:
            # Model requested tool calls
            tool_call_dicts = [
                {
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                }
                for tc in response.tool_calls
            ]
            assistant_msg = ContextEngine.format_assistant_message(
                content=response.content,
                tool_calls=tool_call_dicts,
            )
            return {
                "iteration": iteration,
                "status": AgentStatus.WAITING_FOR_TOOL.value,
                "pending_tool_calls": tool_call_dicts,
                "tool_calls": [*state.get("tool_calls", []), *tool_call_dicts],
                "messages": [*state.get("messages", []), assistant_msg],
            }
        else:
            # Model produced a final response
            assistant_msg = {
                "role": "assistant",
                "content": response.content or "",
            }
            return {
                "iteration": iteration,
                "status": AgentStatus.COMPLETED.value,
                "final_response": response.content,
                "pending_tool_calls": [],
                "messages": [*state.get("messages", []), assistant_msg],
            }

    async def tool_execution_node(state: AgentLoopState) -> dict[str, Any]:
        pending_calls = state.get("pending_tool_calls", [])
        if not pending_calls:
            return {"status": AgentStatus.RUNNING.value}

        tool_calls = [
            ToolCall(
                id=str(tc.get("id", "")),
                name=str(tc.get("name", "")),
                arguments=tc.get("arguments", {}),
            )
            for tc in pending_calls
        ]

        if execution_context is None:
            raise ExecutionContextRequired("AgentRuntime tool execution requires a trusted ExecutionContext")
        ws = workspace or Workspace.create(root_path=".")
        run_id = execution_context.run_id
        aux_metadata = auxiliary_metadata(state.get("metadata", {}) or {})

        results = []
        for call in tool_calls:
            ctx = ToolExecutionContext.from_execution(
                execution_context,
                tool_call_id=call.id,
                workspace=ws,
                metadata=aux_metadata,
            )
            res = await tool_executor.execute(call, context=ctx)
            results.append(res)

            # Record execution observation into working memory
            if memory_orchestrator:
                obs = ExecutionObservation.create(
                    run_id=run_id,
                    tool_name=res.name,
                    tool_call_id=res.tool_call_id,
                    summary=str(res.content)[:200] if res.content else "",
                    is_error=res.is_error,
                )
                try:
                    await memory_orchestrator.record_observation(obs)
                except Exception as oe:
                    logger.warning("Failed to record observation into memory", error=str(oe))

        new_tool_messages = [
            ContextEngine.format_tool_result_message(
                tool_call_id=res.tool_call_id,
                tool_name=res.name,
                content=res.content,
            )
            for res in results
        ]

        result_dicts = [
            {
                "tool_call_id": res.tool_call_id,
                "name": res.name,
                "content": res.content,
                "is_error": res.is_error,
            }
            for res in results
        ]

        return {
            "status": AgentStatus.RUNNING.value,
            "pending_tool_calls": [],
            "tool_results": [*state.get("tool_results", []), *result_dicts],
            "messages": [*state.get("messages", []), *new_tool_messages],
        }

    def route_decision(state: AgentLoopState) -> str:
        """Route conditionally based on model output."""
        if state.get("status") == AgentStatus.FAILED.value:
            return "end"

        if state.get("status") == AgentStatus.WAITING_FOR_TOOL.value and state.get("pending_tool_calls"):
            return "execute_tools"

        return "end"

    builder = StateGraph(AgentLoopState)
    builder.add_node("model", model_node)
    builder.add_node("execute_tools", tool_execution_node)

    builder.add_edge(START, "model")
    builder.add_conditional_edges(
        "model",
        route_decision,
        {"execute_tools": "execute_tools", "end": END},
    )
    builder.add_edge("execute_tools", "model")

    return builder.compile(checkpointer=checkpointer)


class AgentRuntime:
    """Core agent runtime providing loop execution, tool invocation, and state tracking."""

    def __init__(
        self,
        model_gateway: ModelGateway,
        tool_registry: ToolRegistry,
        context_engine: ContextEngine | None = None,
        tool_executor: ToolExecutor | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        default_system_prompt: str = (
            "You are ByteBuddhi, an expert AI programming assistant. "
            "Use available tools when needed to verify information and complete tasks."
        ),
        max_iterations: int = 10,
        workspace: Workspace | None = None,
        memory_orchestrator: MemoryOrchestrator | None = None,
        tracer: Tracer | None = None,
        meter: Meter | None = None,
    ):
        self.model_gateway = model_gateway
        self.tool_registry = tool_registry
        self.context_engine = context_engine or ContextEngine()
        self.tool_executor = tool_executor or ToolExecutor(tool_registry)
        self.checkpointer = checkpointer
        self.default_system_prompt = default_system_prompt
        self.max_iterations = max_iterations
        self.workspace = workspace or Workspace.create(root_path=".")
        self.memory_orchestrator = memory_orchestrator
        self.tracer = tracer or NoOpTracer()
        self.meter = meter or NoOpMeter()

        # Telemetry instruments
        self._runs_counter = self.meter.create_counter(MetricNames.AGENT_RUNS_TOTAL)
        self._failures_counter = self.meter.create_counter(MetricNames.AGENT_RUN_FAILURES_TOTAL)
        self._duration_hist = self.meter.create_histogram(MetricNames.AGENT_RUN_DURATION, unit="ms")
        self._token_hist = self.meter.create_histogram(MetricNames.AGENT_TOKEN_USAGE)

        self.graph = create_agent_loop_graph(
            model_gateway=self.model_gateway,
            tool_registry=self.tool_registry,
            tool_executor=self.tool_executor,
            context_engine=self.context_engine,
            system_prompt=self.default_system_prompt,
            checkpointer=self.checkpointer,
            workspace=self.workspace,
            memory_orchestrator=self.memory_orchestrator,
            execution_context=None,
        )

    async def run(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        execution_context: ExecutionContext | None = None,
        config: RunnableConfig | None = None,
        workspace: Workspace | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_executor: ToolExecutor | None = None,
        max_iterations: int | None = None,
    ) -> AgentRunState:
        """Execute the agent loop for the given messages.

        Args:
            messages: Conversation messages (role and content).
            system_prompt: Optional override for system prompt.
            run_id: Optional unique run identifier.
            metadata: Optional auxiliary metadata. Trusted identity is never read from this dict.
            execution_context: Trusted immutable identity for the run.
            config: Optional LangGraph RunnableConfig (e.g. thread_id for checkpointer).
            workspace: Optional Workspace override for this run.
            tool_registry: Optional ToolRegistry override (e.g. for scoped child capabilities).
            tool_executor: Optional ToolExecutor override.
            max_iterations: Optional per-run iteration limit.

        Returns:
            AgentRunState: Final run state including answer, status, and history.
        """
        if execution_context is None:
            raise ExecutionContextRequired("AgentRuntime.run requires a trusted ExecutionContext")
        active_run_id = execution_context.run_id
        effective_max_iter = max_iterations if max_iterations is not None else self.max_iterations
        run_metadata = auxiliary_metadata(metadata)
        initial_state: AgentLoopState = {
            "run_id": active_run_id,
            "messages": messages,
            "status": AgentStatus.RUNNING.value,
            "iteration": 0,
            "max_iterations": effective_max_iter,
            "pending_tool_calls": [],
            "tool_calls": [],
            "tool_results": [],
            "final_response": None,
            "error": None,
            "metadata": run_metadata,
        }

        # If system prompt, workspace, or tools are customized, compile graph with overrides
        graph_to_use = self.graph
        custom_prompt = system_prompt and system_prompt != self.default_system_prompt
        custom_ws = workspace and workspace != self.workspace
        custom_tools = tool_registry is not None and tool_registry != self.tool_registry
        custom_executor = tool_executor is not None and tool_executor != self.tool_executor
        if custom_prompt or custom_ws or custom_tools or custom_executor or execution_context is not None:
            graph_to_use = create_agent_loop_graph(
                model_gateway=self.model_gateway,
                tool_registry=tool_registry or self.tool_registry,
                tool_executor=tool_executor or self.tool_executor,
                context_engine=self.context_engine,
                system_prompt=system_prompt or self.default_system_prompt,
                checkpointer=self.checkpointer,
                workspace=workspace or self.workspace,
                memory_orchestrator=self.memory_orchestrator,
                execution_context=execution_context,
            )

        run_config = config or {"configurable": {"thread_id": active_run_id}}

        logger.info("Starting AgentRuntime run", run_id=active_run_id)

        start_time = time.perf_counter()
        corr_ctx = get_correlation_context()
        span_user = execution_context.user_id_str
        span_project = execution_context.project_id_str or ""
        span_conversation = execution_context.conversation_id_str or ""
        span_parent = execution_context.parent_run_id or corr_ctx.parent_run_id or ""
        span_child = execution_context.child_run_id or corr_ctx.child_run_id or active_run_id
        span_attrs = {
            SpanAttributes.PARENT_RUN_ID: span_parent,
            SpanAttributes.CHILD_RUN_ID: span_child,
            SpanAttributes.USER_ID: span_user,
            SpanAttributes.PROJECT_ID: span_project,
            SpanAttributes.CONVERSATION_ID: span_conversation,
        }

        parent_span = self.tracer.get_current_span()
        with self.tracer.start_as_current_span(
            SpanNames.AGENT_RUN,
            parent=parent_span,
            attributes=span_attrs,
        ) as span:
            self._runs_counter.add(1, {"agent_role": "generalist", "execution_status": "running"})
            try:
                raw_result = await graph_to_use.ainvoke(initial_state, config=run_config)
                state_res = AgentRunState.from_loop_state(raw_result)

                duration_ms = (time.perf_counter() - start_time) * 1000.0
                status_str = state_res.status.value
                self._duration_hist.record(duration_ms, {"execution_status": status_str})

                total_tokens = state_res.token_usage.total_tokens if state_res.token_usage else 0
                if total_tokens > 0:
                    self._token_hist.record(total_tokens, {"agent_role": "generalist"})

                span.set_attribute(SpanAttributes.EXECUTION_STATUS, status_str)
                if state_res.status == AgentStatus.FAILED:
                    span.set_status(SpanStatus.ERROR, description=str(state_res.error or "Agent run failed"))
                    self._failures_counter.add(1, {"agent_role": "generalist"})
                else:
                    span.set_status(SpanStatus.OK)

                logger.info(
                    "AgentRuntime run finished",
                    run_id=active_run_id,
                    status=status_str,
                    iterations=raw_result.get("iteration"),
                )
                return state_res
            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                self._duration_hist.record(duration_ms, {"execution_status": "failed"})
                self._failures_counter.add(1, {"agent_role": "generalist"})
                span.record_exception(e)
                span.set_status(SpanStatus.ERROR, description=str(e))
                raise
