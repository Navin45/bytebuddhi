"""Command executor coordinating policy checks, workspace boundaries, process execution, and artifact archiving."""

from pathlib import Path

from app.application.policy.command_policy import CommandPolicy
from app.application.ports.output.execution.process_manager import (
    ProcessManager,
    ProcessResult,
)
from app.application.ports.output.logger import get_logger
from app.application.ports.output.storage.artifact_store import ArtifactStore
from app.application.tools.context import ToolExecutionContext
from app.domain.exceptions.workspace_exceptions import CommandBlockedError
from app.domain.models.environment_policy import EnvironmentPolicy
from app.domain.models.workspace import Workspace

logger = get_logger(__name__)


class CommandExecutor:
    """Executes commands safely within a workspace, enforcing policy and archiving output streams."""

    def __init__(
        self,
        process_manager: ProcessManager,
        workspace: Workspace,
        command_policy: CommandPolicy | None = None,
        environment_policy: EnvironmentPolicy | None = None,
        artifact_store: ArtifactStore | None = None,
    ):
        self.process_manager = process_manager
        self.workspace = workspace
        self.command_policy = command_policy or CommandPolicy()
        self.environment_policy = environment_policy or EnvironmentPolicy()
        self.artifact_store = artifact_store

    async def execute(
        self,
        command: list[str] | None = None,
        command_str: str | None = None,
        cwd: str | None = None,
        timeout: float = 30.0,
        context: ToolExecutionContext | None = None,
    ) -> ProcessResult:
        """Execute a command safely with policy enforcement and bounded buffering.

        Args:
            command: Command and arguments as an argv list (strongly preferred).
            command_str: Raw command string (subject to high-risk validation).
            cwd: Working directory relative to workspace root.
            timeout: Timeout in seconds (defaults to 30s).
            context: Optional ToolExecutionContext.

        Returns:
            ProcessResult: Structured outcome with compact previews and artifact references.
        """
        active_ws = context.workspace if context is not None else self.workspace

        # 1. Resolve command format (argv preferred)
        cmd_to_run: list[str] | str
        if command and isinstance(command, list) and len(command) > 0:
            cmd_to_run = command
        elif command_str and isinstance(command_str, str):
            cmd_to_run = command_str.strip()
        else:
            raise ValueError("Either 'command' (argv list) or 'command_str' must be provided.")

        # 2. Policy validation
        allowed, risk, reason = self.command_policy.validate_command(cmd_to_run)
        if not allowed:
            cmd_display = " ".join(cmd_to_run) if isinstance(cmd_to_run, list) else str(cmd_to_run)
            logger.warning("Command execution blocked by policy", command=cmd_display, reason=reason, risk=risk.value)
            raise CommandBlockedError(command=cmd_display, reason=reason or f"Risk tier {risk.value} disallowed")

        # 3. Resolve working directory safely inside workspace
        resolved_cwd: Path = active_ws.resolve_path(cwd) if cwd else active_ws.root_path

        # 4. Build sanitized environment
        env = self.environment_policy.build_env()

        # 5. Execute via ProcessManager
        logger.info(
            "Executing command",
            command=cmd_to_run,
            cwd=str(resolved_cwd),
            timeout=timeout,
        )
        result = await self.process_manager.run(
            command=cmd_to_run,
            cwd=resolved_cwd,
            env=env,
            timeout=timeout,
        )

        # 6. Archive large output streams into ArtifactStore
        if self.artifact_store is not None:
            try:
                if result.stdout_preview or result.stdout_bytes > 0:
                    stdout_art_id = f"{result.execution_id}_stdout.log"
                    # Note: LocalProcessManager provides stdout in result or stream
                    stdout_uri = await self.artifact_store.save_artifact(
                        artifact_id=stdout_art_id,
                        content=result.stdout_preview,
                        metadata={"execution_id": result.execution_id, "stream": "stdout"},
                    )
                    result.stdout_ref = stdout_uri

                if result.stderr_preview or result.stderr_bytes > 0:
                    stderr_art_id = f"{result.execution_id}_stderr.log"
                    stderr_uri = await self.artifact_store.save_artifact(
                        artifact_id=stderr_art_id,
                        content=result.stderr_preview,
                        metadata={"execution_id": result.execution_id, "stream": "stderr"},
                    )
                    result.stderr_ref = stderr_uri
            except Exception as ae:
                logger.warning("Failed to archive execution streams to ArtifactStore", error=str(ae))

        return result
