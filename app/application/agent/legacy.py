"""Legacy agent prototype quarantine.

Contains retired early prototypes (ByteBuddhiAgent, create_agent_graph, AgentNodes)
which are preserved strictly for backward compatibility and test isolation.
All active production code must use canonical AgentRuntime and MultiAgentOrchestrator.
"""

import warnings
from typing import Any, cast

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.application.agent.state import AgentState, IntentType
from app.application.ports.output.llm.llm_provider import LLMProvider
from app.application.ports.output.logger import get_logger

logger = get_logger(__name__)


class AgentNodes:
    """[DEPRECATED] Collection of legacy agent node functions."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        search_service: Any | None = None,
    ):
        warnings.warn(
            "AgentNodes is deprecated and quarantined. Use AgentRuntime instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.llm = llm_provider
        self.search_service = search_service

    async def classify_intent(self, state: AgentState) -> dict:
        user_query = state["user_query"]
        classification_prompt = f"Classify intent for: {user_query}"
        messages = [{"role": "user", "content": classification_prompt}]
        response = await self.llm.generate(messages, temperature=0.0)
        intent = response.strip().lower()
        if intent not in IntentType.all_intents():
            intent = IntentType.GENERAL_CHAT
        return {"intent": intent}

    async def retrieve_context(self, state: AgentState) -> dict:
        retrieved_context: list[dict[str, Any]] = []
        return {"retrieved_context": retrieved_context}

    async def generate_response(self, state: AgentState) -> dict:
        user_query = state["user_query"]
        messages = [{"role": "user", "content": user_query}]
        response = await self.llm.generate(messages)
        updated_messages = state.get("messages", [])
        updated_messages.append(HumanMessage(content=user_query))
        updated_messages.append(AIMessage(content=response))
        return {"explanation": response, "messages": updated_messages}

    async def handle_error(self, state: AgentState) -> dict:
        error_message = "I encountered an error while processing your request."
        updated_messages = state.get("messages", [])
        updated_messages.append(AIMessage(content=error_message))
        return {"explanation": error_message, "messages": updated_messages}


def should_retrieve_context(state: AgentState) -> str:
    """[DEPRECATED] Determine if context retrieval is needed."""
    intent = state.get("intent")
    if intent in [IntentType.CODE_EXPLANATION, IntentType.DEBUGGING, IntentType.REFACTORING]:
        return "retrieve_context"
    return "generate_response"


def create_agent_graph(
    llm_provider: LLMProvider,
    checkpoint_saver: BaseCheckpointSaver | None = None,
    search_service: Any | None = None,
) -> CompiledStateGraph:
    """[DEPRECATED] Create legacy LangGraph agent workflow."""
    warnings.warn(
        "create_agent_graph is deprecated. Use create_agent_loop_graph via AgentRuntime instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    workflow = StateGraph(AgentState)
    nodes = AgentNodes(llm_provider, search_service)
    workflow.add_node("classify_intent", nodes.classify_intent)
    workflow.add_node("retrieve_context", nodes.retrieve_context)
    workflow.add_node("generate_response", nodes.generate_response)
    workflow.set_entry_point("classify_intent")
    workflow.add_conditional_edges("classify_intent", should_retrieve_context)
    workflow.add_edge("retrieve_context", "generate_response")
    workflow.add_edge("generate_response", END)
    return workflow.compile(checkpointer=checkpoint_saver)


class ByteBuddhiAgent:
    """[DEPRECATED] Early prototype agent wrapper."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        checkpoint_saver: BaseCheckpointSaver | None = None,
        search_service: Any | None = None,
    ):
        warnings.warn(
            "ByteBuddhiAgent is deprecated. Use canonical AgentRuntime instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.llm_provider = llm_provider
        self.checkpoint_saver = checkpoint_saver
        self.search_service = search_service
        self.graph = create_agent_graph(llm_provider, checkpoint_saver, search_service)

    async def process_query(
        self,
        user_query: str,
        project_id: str | None = None,
        conversation_history: list[Any] | None = None,
        thread_id: str | None = None,
    ) -> AgentState:
        initial_state: AgentState = {
            "messages": conversation_history or [],
            "user_query": user_query,
            "intent": None,
            "project_id": project_id,
            "retrieved_context": [],
            "search_results": None,
            "generated_code": None,
            "explanation": None,
            "error": None,
            "metadata": {},
        }
        runnable_config: RunnableConfig | None = None
        if thread_id and self.checkpoint_saver:
            runnable_config = {"configurable": {"thread_id": thread_id}}

        try:
            final_state = await self.graph.ainvoke(initial_state, config=runnable_config)
            return cast(AgentState, final_state)
        except Exception as e:
            logger.error("Legacy agent execution failed", error=str(e))
            error_state = initial_state.copy()
            error_state["error"] = str(e)
            nodes = AgentNodes(self.llm_provider)
            error_result = await nodes.handle_error(error_state)
            error_state.update(cast(AgentState, error_result))
            return error_state
