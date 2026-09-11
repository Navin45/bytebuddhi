"""Application registry for managing trusted AgentDefinition specifications."""

from app.domain.models.agent import AgentDefinition, AgentRole
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class AgentRegistry:
    """Central repository of trusted AgentDefinition specifications.

    Security Invariants:
        1. Definitions are strictly registered by trusted application code.
        2. No tool or API allows the model to register, alter, or unregister agents.
        3. Duplicate agent IDs are rejected unless explicit override is permitted.
    """

    def __init__(self) -> None:
        self._definitions: dict[str, AgentDefinition] = {}

    def __len__(self) -> int:
        return len(self._definitions)

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._definitions

    def register(self, definition: AgentDefinition, allow_override: bool = False) -> None:
        """Register a trusted agent definition.

        Args:
            definition: The AgentDefinition to register.
            allow_override: If True, allows updating an existing definition.

        Raises:
            ValueError: If an agent with the same ID is already registered and allow_override is False.
        """
        agent_id = definition.id.strip()
        if not agent_id:
            raise ValueError("AgentDefinition ID cannot be empty")

        if agent_id in self._definitions and not allow_override:
            raise ValueError(
                f"AgentDefinition '{agent_id}' is already registered. "
                "Cannot overwrite without explicit allow_override=True."
            )

        self._definitions[agent_id] = definition
        logger.info("Registered AgentDefinition", agent_id=agent_id, role=definition.role.value)

    def unregister(self, agent_id: str) -> bool:
        """Unregister an agent definition.

        Returns:
            bool: True if removed, False if not found.
        """
        if agent_id in self._definitions:
            del self._definitions[agent_id]
            logger.info("Unregistered AgentDefinition", agent_id=agent_id)
            return True
        return False

    def get(self, agent_id: str) -> AgentDefinition | None:
        """Look up an agent definition by its unique ID."""
        return self._definitions.get(agent_id.strip())

    def has(self, agent_id: str) -> bool:
        """Check if an agent definition exists."""
        return agent_id.strip() in self._definitions

    def list_agents(self, role: AgentRole | None = None) -> list[AgentDefinition]:
        """List registered agent definitions with optional role filtering."""
        if role is None:
            return list(self._definitions.values())
        return [d for d in self._definitions.values() if d.role == role]


def create_default_registry() -> AgentRegistry:
    """Create and pre-populate an AgentRegistry with standard trusted specialists."""
    registry = AgentRegistry()

    # 1. Researcher — Read-only code and external repository inspection
    registry.register(
        AgentDefinition(
            id="researcher",
            name="Research Specialist",
            description="Specialized in inspecting codebase files, code symbols, documentation, and repositories.",
            role=AgentRole.RESEARCHER,
            system_prompt=(
                "You are ByteBuddhi's Research Specialist. Your responsibility is to inspect codebases, "
                "analyze code symbols, search files, and examine repository structures thoroughly. "
                "You only perform read-only analysis; you do not mutate files or execute arbitrary OS commands."
            ),
            allowed_capabilities=(
                "read_file",
                "list_directory",
                "code_symbol_search",
                "code_structure_summary",
                "code_find_references",
                "code_file_outline",
                "github_search_repositories",
                "github_get_repository",
                "github_list_issues",
                "github_get_issue",
                "github_list_pull_requests",
                "github_get_pull_request",
            ),
            can_delegate=False,
            is_mutating=False,
        )
    )

    # 2. Coder — Code editing, workspace file manipulation, code intelligence
    registry.register(
        AgentDefinition(
            id="coder",
            name="Coding Specialist",
            description="Specialized in writing code, editing files, refactoring, and verifying local syntax.",
            role=AgentRole.CODER,
            system_prompt=(
                "You are ByteBuddhi's Coding Specialist. Your responsibility is to write clean, maintainable, "
                "production-quality code. Follow project style guidelines, ensure strict typing, and modify only "
                "files within the workspace boundary."
            ),
            allowed_capabilities=(
                "read_file",
                "write_file",
                "create_directory",
                "list_directory",
                "code_symbol_search",
                "code_structure_summary",
                "code_find_references",
                "code_file_outline",
                "run_command",
            ),
            can_delegate=False,
            is_mutating=True,
        )
    )

    # 3. Reviewer — Strict read-only auditing and security/quality review
    registry.register(
        AgentDefinition(
            id="reviewer",
            name="Review Specialist",
            description="Specialized in auditing code changes for correctness, security, edge cases, and design.",
            role=AgentRole.REVIEWER,
            system_prompt=(
                "You are ByteBuddhi's Review Specialist. Your responsibility is to audit code changes with extreme rigor. "
                "Look for race conditions, security vulnerabilities, authorization flaws, edge cases, and architectural "
                "regressions. You do not modify files."
            ),
            allowed_capabilities=(
                "read_file",
                "list_directory",
                "code_symbol_search",
                "code_structure_summary",
                "code_find_references",
                "code_file_outline",
            ),
            can_delegate=False,
            is_mutating=False,
        )
    )

    # 4. Tester — Test execution and diagnostic verification
    registry.register(
        AgentDefinition(
            id="tester",
            name="Testing Specialist",
            description="Specialized in running test suites, verifying pass/fail outcomes, and diagnosing failures.",
            role=AgentRole.TESTER,
            system_prompt=(
                "You are ByteBuddhi's Testing Specialist. Your responsibility is to run tests, inspect test failures, "
                "and verify regression safety. You execute test commands safely within the workspace."
            ),
            allowed_capabilities=(
                "read_file",
                "list_directory",
                "run_command",
                "code_symbol_search",
            ),
            can_delegate=False,
            is_mutating=False,
        )
    )

    # 5. Planner — Task decomposition and coordination
    registry.register(
        AgentDefinition(
            id="planner",
            name="Planning Specialist",
            description="Specialized in decomposing complex multi-step objectives and coordinating specialist agents.",
            role=AgentRole.PLANNER,
            system_prompt=(
                "You are ByteBuddhi's Planning Specialist. Your responsibility is to break down complex goals into "
                "focused subtasks and coordinate specialist agents to achieve the objective."
            ),
            allowed_capabilities=(
                "read_file",
                "list_directory",
                "delegate_task",
            ),
            can_delegate=True,
            is_mutating=False,
        )
    )

    return registry
