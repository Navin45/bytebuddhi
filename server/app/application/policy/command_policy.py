"""Command risk classification, safety policies, and approval hooks."""

from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

# Common shell and language interpreters treated as high risk
INTERPRETERS_AND_SHELLS: set[str] = {
    "python",
    "python3",
    "python.exe",
    "node",
    "node.exe",
    "bash",
    "sh",
    "zsh",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "cmd",
    "cmd.exe",
    "perl",
    "ruby",
    "php",
}

READ_ONLY_COMMANDS: set[str] = {
    "ls",
    "dir",
    "cat",
    "type",
    "head",
    "tail",
    "pwd",
    "find",
    "grep",
    "rg",
    "echo",
    "which",
    "where",
    "whoami",
    "git",  # subcommands evaluated separately
}

READ_ONLY_GIT_SUBCOMMANDS: set[str] = {
    "status",
    "log",
    "diff",
    "branch",
    "show",
    "rev-parse",
    "describe",
}

DESTRUCTIVE_PATTERNS: list[str] = [
    "rm -rf /",
    "rm -rf /*",
    "rm -rf --no-preserve-root",
    "del /s /q c:\\",
    "del /s /q c:/",
    "format c:",
    "mkfs",
    ":(){ :|:& };:",
    "shutdown",
    "init 0",
    "dd if=/dev/zero",
]


class CommandRiskLevel(StrEnum):
    """Risk tier for command execution."""

    READ_ONLY = "read_only"
    MODIFYING = "modifying"
    NETWORK_OR_PACKAGE = "network_or_package"
    HIGH_RISK = "high_risk"
    DESTRUCTIVE = "destructive"


@runtime_checkable
class ApprovalHook(Protocol):
    """Hook interface for verifying whether high-risk operations are approved."""

    def is_approved(self, command: list[str] | str, risk: CommandRiskLevel) -> bool:
        """Return True if command execution is authorized."""
        ...


class CommandPolicy:
    """Classifies commands and enforces safety boundaries and approval requirements."""

    def __init__(
        self,
        approval_hook: ApprovalHook | None = None,
        allow_high_risk: bool = False,
    ):
        self.approval_hook = approval_hook
        self.allow_high_risk = allow_high_risk

    def classify(self, command: list[str] | str) -> CommandRiskLevel:
        """Determine the risk tier of a given command."""
        cmd_str = " ".join(command) if isinstance(command, list) else str(command)
        cmd_lower = cmd_str.strip().lower()

        # 1. Check for destructive patterns
        for pattern in DESTRUCTIVE_PATTERNS:
            if pattern in cmd_lower:
                return CommandRiskLevel.DESTRUCTIVE

        # Extract executable name
        if isinstance(command, list):
            exe = Path(command[0]).name.lower() if command else ""
            args = [a.lower() for a in command[1:]]
        else:
            parts = cmd_lower.split()
            exe = Path(parts[0]).name.lower() if parts else ""
            args = parts[1:]

        # 2. Check for shells and interpreters
        if exe in INTERPRETERS_AND_SHELLS:
            return CommandRiskLevel.HIGH_RISK

        # 3. Check for package managers / network commands
        if exe in {"pip", "npm", "yarn", "pnpm", "uv", "cargo", "curl", "wget"}:
            return CommandRiskLevel.NETWORK_OR_PACKAGE

        # 4. Check for git commands
        if exe == "git":
            subcmd = args[0] if args else ""
            if subcmd in READ_ONLY_GIT_SUBCOMMANDS:
                return CommandRiskLevel.READ_ONLY
            return CommandRiskLevel.MODIFYING

        # 5. Check for read-only commands
        if exe in READ_ONLY_COMMANDS:
            return CommandRiskLevel.READ_ONLY

        # Default non-classified commands to MODIFYING
        return CommandRiskLevel.MODIFYING

    def validate_command(self, command: list[str] | str) -> tuple[bool, CommandRiskLevel, str | None]:
        """Validate command execution against policy.

        Returns:
            tuple[bool, CommandRiskLevel, Optional[str]]: (is_allowed, risk_level, rejection_reason)
        """
        risk = self.classify(command)

        # Destructive commands are blocked unconditionally
        if risk == CommandRiskLevel.DESTRUCTIVE:
            return False, risk, "Destructive system commands are prohibited"

        # High-risk commands require explicit policy flag or approval hook
        if risk == CommandRiskLevel.HIGH_RISK:
            if self.approval_hook is not None:
                if not self.approval_hook.is_approved(command, risk):
                    return False, risk, "High-risk command requires approval but was not approved"
            elif not self.allow_high_risk:
                return (
                    False,
                    risk,
                    "Shells and interpreters are classified as high-risk and blocked by default policy",
                )

        return True, risk, None
