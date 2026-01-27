"""LangGraph agent graph construction.

This module builds the LangGraph agent by connecting nodes into
a directed graph that defines the agent's workflow.
"""

from typing import Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph

from app.application.agent.nodes import AgentNodes
from app.application.agent.state import AgentState, IntentType
from app.application.ports.output.llm.llm_provider import LLMProvider
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


def should_retrieve_context(state: AgentState) -> str:
    """Determine if context retrieval is needed.
    
    This conditional edge decides whether to retrieve code context
    based on the classified intent.
    
    Args:
        state: Current agent state
        
    Returns:
        str: Next node name ('retrieve_context' or 'generate_response')
    """
    intent = state.get("intent")
    
    # Retrieve context for code-related intents
    if intent in [
        IntentType.CODE_EXPLANATION,
        IntentType.CODE_DEBUG,
        IntentType.CODE_REFACTOR,
    ]:
        return "retrieve_context"
    
    # Skip context retrieval for other intents
    return "generate_response"


def create_agent_graph(
    llm_provider: LLMProvider,
    checkpoint_saver: Optional[BaseCheckpointSaver] = None,
) -> StateGraph:
    """Create the ByteBuddhi agent graph.
    
    This function constructs the LangGraph agent by defining nodes
    and edges that represent the agent's workflow.
    
    The workflow is:
    1. Classify user intent
    2. Conditionally retrieve code context
    3. Generate response
    4. Handle errors if they occur
    
    Args:
        llm_provider: LLM provider for the agent
        checkpoint_saver: Optional checkpoint saver for state persistence
        
    Returns:
        StateGraph: Compiled agent graph ready for execution
    """
    logger.info("Creating agent graph", with_checkpoints=checkpoint_saver is not None)
    
    # Initialize nodes
    nodes = AgentNodes(llm_provider)
    
    # Create graph
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("classify_intent", nodes.classify_intent)
    workflow.add_node("retrieve_context", nodes.retrieve_context)
    workflow.add_node("generate_response", nodes.generate_response)
    workflow.add_node("handle_error", nodes.handle_error)
    
    # Set entry point
    workflow.set_entry_point("classify_intent")
    
    # Add edges
    # After classification, decide whether to retrieve context
    workflow.add_conditional_edges(
        "classify_intent",
        should_retrieve_context,
        {
            "retrieve_context": "retrieve_context",
            "generate_response": "generate_response",
        },
    )
    
    # After retrieving context, generate response
    workflow.add_edge("retrieve_context", "generate_response")
    
    # After generating response, end
    workflow.add_edge("generate_response", END)
    
    # Error handling ends the workflow
    workflow.add_edge("handle_error", END)
    
    # Compile graph with optional checkpoint saver
    compile_kwargs = {}
    if checkpoint_saver:
        compile_kwargs["checkpointer"] = checkpoint_saver
        logger.info("Agent graph compiled with checkpoint persistence")
    
    graph = workflow.compile(**compile_kwargs)
    
    logger.info("Agent graph created successfully")
    
    return graph


class ByteBuddhiAgent:
    """ByteBuddhi coding agent.
    
    This class wraps the LangGraph agent and provides a simple
    interface for processing user queries with optional state persistence.
    
    Attributes:
        graph: Compiled LangGraph agent
        llm_provider: LLM provider for the agent
        checkpoint_saver: Optional checkpoint saver for persistence
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        checkpoint_saver: Optional[BaseCheckpointSaver] = None,
    ):
        """Initialize the agent.
        
        Args:
            llm_provider: LLM provider for the agent
            checkpoint_saver: Optional checkpoint saver for state persistence
        """
        self.llm_provider = llm_provider
        self.checkpoint_saver = checkpoint_saver
        self.graph = create_agent_graph(llm_provider, checkpoint_saver)

    async def process_query(
        self,
        user_query: str,
        project_id: str = None,
        conversation_history: list = None,
        thread_id: str = None,
    ) -> AgentState:
        """Process a user query through the agent.
        
        Args:
            user_query: User's question or request
            project_id: Optional project ID for context
            conversation_history: Optional conversation history
            thread_id: Optional thread ID for checkpoint persistence
            
        Returns:
            AgentState: Final agent state with response
        """
        logger.info("Processing user query", project_id=project_id, thread_id=thread_id)
        
        # Initialize state
        initial_state: AgentState = {
            "messages": conversation_history or [],
            "user_query": user_query,
            "intent": None,
            "project_id": project_id,
            "retrieved_context": [],
            "generated_code": None,
            "explanation": None,
            "error": None,
            "metadata": {},
        }
        
        # Build config with optional thread_id for checkpoints
        config = {}
        if thread_id and self.checkpoint_saver:
            config["configurable"] = {"thread_id": thread_id}
            logger.info("Using checkpoint persistence", thread_id=thread_id)
        
        try:
            # Run agent
            final_state = await self.graph.ainvoke(initial_state, config=config)
            return final_state
            
        except Exception as e:
            logger.error("Agent execution failed", error=str(e))
            
            # Run error handler
            error_state = initial_state.copy()
            error_state["error"] = str(e)
            
            nodes = AgentNodes(self.llm_provider)
            error_result = await nodes.handle_error(error_state)
            error_state.update(error_result)
            
            return error_state

    async def resume_conversation(
        self,
        thread_id: str,
        user_query: str,
    ) -> AgentState:
        """Resume a conversation from a checkpoint.
        
        This method retrieves the last checkpoint for a thread and
        continues the conversation from that point.
        
        Args:
            thread_id: Thread ID to resume
            user_query: New user query to process
            
        Returns:
            AgentState: Final agent state with response
        """
        if not self.checkpoint_saver:
            logger.warning("Cannot resume conversation without checkpoint saver")
            return await self.process_query(user_query, thread_id=thread_id)
        
        logger.info("Resuming conversation", thread_id=thread_id)
        
        # Process query with thread_id to load checkpoint
        return await self.process_query(
            user_query=user_query,
            thread_id=thread_id,
        )
