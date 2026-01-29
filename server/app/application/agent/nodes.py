"""LangGraph agent nodes.

This module implements the individual nodes (functions) that make up
the ByteBuddhi agent graph. Each node performs a specific task in the
agent's workflow.
"""

from typing import Dict, Optional

from langchain_core.messages import AIMessage, HumanMessage

from app.application.agent.state import AgentState, IntentType
from app.application.ports.output.llm.llm_provider import LLMProvider
from app.infrastructure.config.logger import get_logger
from app.infrastructure.external.tavily_search import TavilySearchService

logger = get_logger(__name__)


class AgentNodes:
    """Collection of agent node functions.
    
    Each method in this class represents a node in the LangGraph agent.
    Nodes take the current state and return an updated state.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        search_service: Optional[TavilySearchService] = None,
    ):
        """Initialize agent nodes with LLM provider and search service.
        
        Args:
            llm_provider: LLM provider for generating responses
            search_service: Optional Tavily search service for web searches
        """
        self.llm = llm_provider
        self.search_service = search_service

    async def classify_intent(self, state: AgentState) -> Dict:
        """Classify the user's intent.
        
        This node analyzes the user query to determine what type of
        assistance they need (code generation, explanation, debugging, etc.).
        
        Args:
            state: Current agent state
            
        Returns:
            Dict: Updated state with classified intent
        """
        logger.info("Classifying user intent")
        
        user_query = state["user_query"]
        
        # Build classification prompt
        classification_prompt = f"""Classify the following user request into one of these categories:
- code_generation: User wants to generate new code
- code_explanation: User wants to understand existing code
- code_debug: User needs help debugging an issue
- code_refactor: User wants to improve/refactor code
- question_answer: User has a general programming question
- web_search: User is asking about current information, latest updates, or needs real-time data
- general_chat: General conversation

User request: {user_query}

Respond with only the category name."""

        # Get classification from LLM
        messages = [{"role": "user", "content": classification_prompt}]
        intent = await self.llm.generate(messages)
        intent = intent.strip().lower()
        
        # Validate intent
        if intent not in IntentType.all_intents():
            logger.warning(f"Unknown intent: {intent}, defaulting to general_chat")
            intent = IntentType.GENERAL_CHAT
        
        logger.info(f"Classified intent: {intent}")
        
        return {"intent": intent}

    async def retrieve_context(self, state: AgentState) -> Dict:
        """Retrieve relevant code context from vector store.
        
        This node searches the vector store for code chunks relevant
        to the user's query.
        
        Note: Vector store retrieval will be implemented when the
        vector store repository is complete.
        
        Args:
            state: Current agent state
            
        Returns:
            Dict: Updated state with retrieved context
        """
        logger.info("Retrieving code context")
        
        # Placeholder: return empty context until vector store is implemented
        retrieved_context = []
        
        logger.info(f"Retrieved {len(retrieved_context)} code chunks")
        
        return {"retrieved_context": retrieved_context}

    async def web_search(self, state: AgentState) -> Dict:
        """Perform web search using Tavily.
        
        This node uses the Tavily API to search the web for information
        relevant to the user's query.
        
        Args:
            state: Current agent state
            
        Returns:
            Dict: Updated state with search results
        """
        logger.info("Performing web search")
        
        if not self.search_service:
            logger.warning("Web search requested but Tavily service not configured")
            return {
                "search_results": None,
                "error": "Web search is not configured",
            }
        
        user_query = state["user_query"]
        
        try:
            # Perform search
            search_response = await self.search_service.search(
                query=user_query,
                include_answer=True,
            )
            
            logger.info(
                "Web search completed",
                num_results=len(search_response.get("results", [])),
            )
            
            return {"search_results": search_response}
            
        except Exception as e:
            logger.error("Web search failed", error=str(e))
            return {
                "search_results": None,
                "error": f"Web search failed: {str(e)}",
            }

    async def generate_response(self, state: AgentState) -> Dict:
        """Generate the final response to the user.
        
        This node uses the LLM to generate a response based on the
        user query, intent, and retrieved context.
        
        Args:
            state: Current agent state
            
        Returns:
            Dict: Updated state with generated response
        """
        logger.info("Generating response")
        
        user_query = state["user_query"]
        intent = state.get("intent", IntentType.GENERAL_CHAT)
        context = state.get("retrieved_context", [])
        search_results = state.get("search_results")
        
        # Build response prompt based on intent
        if intent == IntentType.CODE_GENERATION:
            system_prompt = "You are an expert programmer. Generate clean, well-documented code based on the user's request."
        elif intent == IntentType.CODE_EXPLANATION:
            system_prompt = "You are an expert programmer. Explain code clearly and concisely."
        elif intent == IntentType.CODE_DEBUG:
            system_prompt = "You are an expert debugger. Help identify and fix issues in code."
        elif intent == IntentType.CODE_REFACTOR:
            system_prompt = "You are an expert in code quality. Suggest improvements and refactorings."
        elif intent == IntentType.WEB_SEARCH:
            system_prompt = "You are a helpful assistant with access to current web information. Provide accurate, up-to-date answers based on the search results."
        else:
            system_prompt = "You are a helpful programming assistant."
        
        # Add context if available
        context_text = ""
        if context:
            context_text = "\n\nRelevant code context:\n" + "\n\n".join(
                [f"```\n{chunk.get('content', '')}\n```" for chunk in context]
            )
        
        # Add search results if available
        if search_results and self.search_service:
            search_context = self.search_service.format_results_for_context(search_results)
            context_text += f"\n\n{search_context}"
        
        # Build messages
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query + context_text},
        ]
        
        # Generate response
        response = await self.llm.generate(messages)
        
        logger.info("Response generated successfully")
        
        # Update messages history
        updated_messages = state.get("messages", [])
        updated_messages.append(HumanMessage(content=user_query))
        updated_messages.append(AIMessage(content=response))
        
        return {
            "explanation": response,
            "messages": updated_messages,
        }

    async def handle_error(self, state: AgentState) -> Dict:
        """Handle errors that occur during agent execution.
        
        This node generates a user-friendly error message when
        something goes wrong.
        
        Args:
            state: Current agent state
            
        Returns:
            Dict: Updated state with error message
        """
        logger.error("Handling agent error", error=state.get("error"))
        
        error_message = "I encountered an error while processing your request. Please try again or rephrase your question."
        
        updated_messages = state.get("messages", [])
        updated_messages.append(AIMessage(content=error_message))
        
        return {
            "explanation": error_message,
            "messages": updated_messages,
        }
