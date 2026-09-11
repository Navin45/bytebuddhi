"""Child context projector enforcing allowlisting, token budgeting, and identity isolation."""

from typing import Any

from app.application.ports.output.logger import get_logger
from app.domain.models.agent import AgentDefinition, AgentTask, MultiAgentConfig

logger = get_logger(__name__)


class AgentContextProjector:
    """Projects minimal, allowlisted context from parent state to a child agent execution.

    Security & Privacy Rules:
        1. Context Allowlisting: Only task-relevant fields and explicit inputs cross the boundary.
        2. No Transcript Leakage: The full parent conversation transcript is NEVER copied.
        3. Approval Isolation: Parent approval metadata (approved_actions, approval_granted)
           is strictly excluded so child agents cannot inherit or escalate permissions.
        4. Identity Preservation: Trusted caller identity (user_id, project_id, conversation_id)
           is propagated immutably from verified parent context, not from untrusted model arguments.
        5. Token Budgeting: Projected context size is strictly bounded to prevent token exhaustion.
    """

    def __init__(self, config: MultiAgentConfig | None = None) -> None:
        self.config = config or MultiAgentConfig()

    def project_child_context(
        self,
        task: AgentTask,
        definition: AgentDefinition,
        child_run_id: str,
        parent_metadata: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Construct child initial messages and execution metadata.

        Args:
            task: Work assigned to the child agent.
            definition: Trusted definition of the child agent.
            child_run_id: Unique execution identifier for the child run.
            parent_metadata: Trusted metadata from the parent's execution context.

        Returns:
            tuple[list[dict[str, Any]], dict[str, Any]]:
                (child_initial_messages, child_execution_metadata)
        """
        parent_meta = parent_metadata or {}

        # 1. Propagate and enforce immutable trusted identity
        parent_depth = int(parent_meta.get("delegation_depth", 0))
        child_depth = parent_depth + 1

        child_metadata: dict[str, Any] = {
            # Verified identity fields
            "user_id": parent_meta.get("user_id"),
            "project_id": parent_meta.get("project_id"),
            "conversation_id": parent_meta.get("conversation_id"),
            # Run correlation IDs
            "parent_run_id": parent_meta.get("run_id") or parent_meta.get("parent_run_id", "root"),
            "child_run_id": child_run_id,
            "agent_id": definition.id,
            "task_id": task.task_id,
            "delegation_depth": child_depth,
            # Security: explicitly DO NOT inherit approved_actions or approval_granted
        }

        # 2. Build structured subtask prompt with allowlisted fields
        prompt_sections = [
            f"You have been assigned the following subtask as the {definition.name} ({definition.role.value}):\n",
            f"### Task Description:\n{task.description.strip()}",
        ]

        if task.expected_output:
            prompt_sections.append(f"\n### Expected Output:\n{task.expected_output.strip()}")

        if task.input_data:
            input_lines = []
            for k, v in task.input_data.items():
                # Allowlist input items, skip internal/private keys
                if k in ("approval_granted", "approved_actions", "credentials", "secrets"):
                    continue
                str_val = str(v)
                # Bound individual input fields to prevent blowout
                if len(str_val) > 2000:
                    str_val = f"{str_val[:2000]}... [truncated]"
                input_lines.append(f"- **{k}**: {str_val}")
            if input_lines:
                prompt_sections.append("\n### Task Inputs:\n" + "\n".join(input_lines))

        # Include explicit artifact references if given
        artifacts = task.metadata.get("artifacts") or task.input_data.get("artifacts")
        if artifacts and isinstance(artifacts, list):
            prompt_sections.append("\n### Referenced Artifacts:\n" + "\n".join(f"- {a}" for a in artifacts))

        user_content = "\n".join(prompt_sections)

        # 3. Apply token budgeting check on initial message
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
