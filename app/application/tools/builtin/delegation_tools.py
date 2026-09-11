"""Delegation tool allowing models to delegate focused subtasks to specialist agents."""

from typing import Any
from uuid import uuid4

from app.application.agent.orchestrator import MultiAgentOrchestrator
from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import CapabilityType, RiskLevel, ToolDefinition
from app.domain.models.agent import AgentTask, TaskExecutionStatus
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


def create_delegation_tool(orchestrator: MultiAgentOrchestrator) -> tuple[ToolDefinition, Any]:
    """Create the delegate_task capability definition and handler.

    Security & Boundary Invariants:
        1. Target agent_id must exist in the trusted AgentRegistry.
        2. Delegation depth is validated against max_delegation_depth.
        3. Model cannot modify the target agent's system prompt or capabilities.
        4. Parent approval metadata is not inherited by the delegated child.
        5. The tool call is subject to standard ToolPolicyEngine and ToolExecutor boundaries.
    """
    definition = ToolDefinition(
        name="delegate_task",
        description=(
            "Delegate a focused subtask to an approved specialist agent (e.g. 'researcher', 'coder', 'reviewer', 'tester'). "
            "Returns a structured summary of the specialist's findings or code output."
        ),
        parameters={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "ID of the target specialist agent (e.g. 'researcher', 'coder', 'reviewer', 'tester')",
                },
                "task_description": {
                    "type": "string",
                    "description": "Detailed instructions for the specialist subtask",
                },
                "expected_output": {
                    "type": "string",
                    "description": "Optional description of the expected format or deliverable",
                },
                "is_critical": {
                    "type": "boolean",
                    "description": "Whether failure of this subtask should fail the overall workflow (default true)",
                },
            },
            "required": ["agent_id", "task_description"],
        },
        id="native.delegate_task",
        capability_type=CapabilityType.NATIVE,
        risk_level=RiskLevel.MEDIUM,
        requires_approval=False,
    )

    async def delegate_task_handler(
        agent_id: str,
        task_description: str,
        expected_output: str | None = None,
        is_critical: bool = True,
        context: ToolExecutionContext | None = None,
        **kwargs: Any,
    ) -> str:
        """Handler for model-invoked task delegation."""
        if context and context.is_cancelled:
            return "Delegation cancelled before execution."

        task_id = f"task_{agent_id}_{uuid4().hex[:6]}"
        task = AgentTask(
            task_id=task_id,
            agent_id=agent_id.strip().lower(),
            description=task_description,
            expected_output=expected_output,
            is_critical=is_critical,
        )

        logger.info(
            "Executing delegated task via tool call",
            task_id=task_id,
            target_agent=task.agent_id,
            parent_run_id=context.run_id if context else "unknown",
        )

        result = await orchestrator.execute_task(
            task=task,
            parent_context=context,
        )

        if result.status == TaskExecutionStatus.SUCCESS:
            return result.to_compact_summary()
        elif result.status == TaskExecutionStatus.CANCELLED:
            return f"Error: Subtask '{task_id}' was cancelled: {result.error}"
        elif result.status == TaskExecutionStatus.TIMEOUT:
            return f"Error: Subtask '{task_id}' timed out: {result.error}"
        else:
            return f"Error: Subtask '{task_id}' failed: {result.error}"

    return definition, delegate_task_handler
