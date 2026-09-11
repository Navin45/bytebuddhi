"""Child context projector enforcing allowlisting, token budgeting, and identity isolation."""

from typing import Any

from app.application.ports.output.logger import get_logger
from app.domain.exceptions.execution_exceptions import ExecutionContextRequired
from app.domain.models.agent import AgentDefinition, AgentTask, MultiAgentConfig
from app.domain.models.execution_context import ExecutionContext

logger = get_logger(__name__)


class AgentContextProjector:
    """Projects minimal, allowlisted context from parent state to a child agent execution.

    Security & Privacy Rules:
        1. Context Allowlisting: Only task-relevant fields and explicit inputs cross the boundary.
        2. No Transcript Leakage: The full parent conversation transcript is NEVER copied.
        3. Approval Isolation: Parent approval metadata (approved_actions, approval_granted)
           is strictly excluded so child agents cannot inherit or escalate permissions.
        4. Identity Preservation: Trusted caller identity is taken only from ExecutionContext.
        5. Token Budgeting: Projected context size is strictly bounded to prevent token exhaustion.
    """

    def __init__(self, config: MultiAgentConfig | None = None) -> None:
        self.config = config or MultiAgentConfig()

    def project_child_context(
        self,
        task: AgentTask,
        definition: AgentDefinition,
        child_run_id: str,
        parent_execution: ExecutionContext,
        parent_metadata: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Construct child initial messages and auxiliary execution metadata.

        Trusted identity is not copied into metadata. Callers must pass the derived
        child ExecutionContext into AgentRuntime separately.
        """
        if parent_execution is None:
            raise ExecutionContextRequired(
                "AgentContextProjector.project_child_context requires a trusted ExecutionContext"
            )
        # Auxiliary parent metadata is accepted for API compatibility but is never
        # an identity source. Identity keys must not be copied into child metadata.
        _ = parent_metadata

        child_metadata: dict[str, Any] = {
            "agent_id": definition.id,
            "task_id": task.task_id,
        }

        prompt_sections = [
            f"You have been assigned the following subtask as the {definition.name} ({definition.role.value}):\n",
            f"### Task Description:\n{task.description.strip()}",
        ]

        if task.expected_output:
            prompt_sections.append(f"\n### Expected Output:\n{task.expected_output.strip()}")

        if task.input_data:
            input_lines = []
            for k, v in task.input_data.items():
                if k in ("approval_granted", "approved_actions", "credentials", "secrets"):
                    continue
                str_val = str(v)
                if len(str_val) > 2000:
                    str_val = f"{str_val[:2000]}... [truncated]"
                input_lines.append(f"- **{k}**: {str_val}")
            if input_lines:
                prompt_sections.append("\n### Task Inputs:\n" + "\n".join(input_lines))

        artifacts = task.metadata.get("artifacts") or task.input_data.get("artifacts")
        if artifacts and isinstance(artifacts, list):
            prompt_sections.append("\n### Referenced Artifacts:\n" + "\n".join(f"- {a}" for a in artifacts))

        user_content = "\n".join(prompt_sections)

        estimated_tokens = len(user_content) // 4
        max_prompt_tokens = definition.token_budget or (self.config.max_child_tokens // 2)

        if estimated_tokens > max_prompt_tokens:
            max_chars = max_prompt_tokens * 4
            logger.warning(
                "Projected child context exceeds budget, truncating safely",
                task_id=task.task_id,
                estimated_tokens=estimated_tokens,
                max_prompt_tokens=max_prompt_tokens,
            )
            user_content = user_content[:max_chars] + "\n\n[Context truncated to adhere to child token budget]"

        child_messages: list[dict[str, Any]] = [
            {"role": "user", "content": user_content},
        ]

        return child_messages, child_metadata
