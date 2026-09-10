"""AgentRuntime for ByteBuddhi.

Provides the inner agent execution loop orchestrated via LangGraph.
"""

from typing import Any
from uuid import uuid4

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
from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import ToolCall
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry
from app.domain.models.memory import ExecutionObservation, MemoryScope
from app.domain.models.workspace import Workspace
from app.infrastructure.config.logger import get_logger

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
            run_id = state.get("run_id", "")
            meta = state.get("metadata", {})
            scopes = [(MemoryScope.AGENT_RUN, run_id)]
            if project_id := meta.get("project_id"):
                scopes.append((MemoryScope.PROJECT, str(project_id)))
            if user_id := meta.get("user_id"):
                scopes.append((MemoryScope.USER, str(user_id)))

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

        ws = workspace or Workspace.create(root_path=".")
        run_id = state.get("run_id", "")

        # Execute tools safely with ToolExecutionContext
        results = []
        for call in tool_calls:
            ctx = ToolExecutionContext(
                run_id=run_id,
                tool_call_id=call.id,
                workspace=ws,
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

        self.graph = create_agent_loop_graph(
            model_gateway=self.model_gateway,
            tool_registry=self.tool_registry,
            tool_executor=self.tool_executor,
            context_engine=self.context_engine,
            system_prompt=self.default_system_prompt,
            checkpointer=self.checkpointer,
            workspace=self.workspace,
            memory_orchestrator=self.memory_orchestrator,
        )

    async def run(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        config: RunnableConfig | None = None,
        workspace: Workspace | None = None,
    ) -> AgentRunState:
        """Execute the agent loop for the given messages.

        Args:
            messages: Conversation messages (role and content).
            system_prompt: Optional override for system prompt.
            run_id: Optional unique run identifier.
            metadata: Optional metadata dictionary.
            config: Optional LangGraph RunnableConfig (e.g. thread_id for checkpointer).
            workspace: Optional Workspace override for this run.

        Returns:
            AgentRunState: Final run state including answer, status, and history.
        """
        active_run_id = run_id or f"run_{uuid4().hex[:12]}"
        initial_state: AgentLoopState = {
            "run_id": active_run_id,
            "messages": messages,
            "status": AgentStatus.RUNNING.value,
            "iteration": 0,
            "max_iterations": self.max_iterations,
            "pending_tool_calls": [],
            "tool_calls": [],
            "tool_results": [],
            "final_response": None,
            "error": None,
            "metadata": metadata or {},
        }

        # If system prompt or workspace is customized, we compile with it
        graph_to_use = self.graph
        custom_prompt = system_prompt and system_prompt != self.default_system_prompt
        custom_ws = workspace and workspace != self.workspace
        if custom_prompt or custom_ws:
            graph_to_use = create_agent_loop_graph(
                model_gateway=self.model_gateway,
                tool_registry=self.tool_registry,
                tool_executor=self.tool_executor,
                context_engine=self.context_engine,
                system_prompt=system_prompt or self.default_system_prompt,
                checkpointer=self.checkpointer,
                workspace=workspace or self.workspace,
            )

        run_config = config or {"configurable": {"thread_id": active_run_id}}

        logger.info("Starting AgentRuntime run", run_id=active_run_id)
        raw_result = await graph_to_use.ainvoke(initial_state, config=run_config)
        logger.info(
            "AgentRuntime run finished",
            run_id=active_run_id,
            status=raw_result.get("status"),
            iterations=raw_result.get("iteration"),
        )

        return AgentRunState.from_loop_state(raw_result)
