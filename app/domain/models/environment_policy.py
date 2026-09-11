"""Environment variable sanitization and allowlisting policy."""

import os
import re
from dataclasses import dataclass, field

# Standard system runtime environment variables safe to inherit
STANDARD_ALLOWLIST: set[str] = {
    # Cross-platform common
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TZ",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SHELL",
    # Windows system specifics
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "USERPROFILE",
    "USERNAME",
    "HOMEDRIVE",
    "HOMEPATH",
    "ALLUSERSPROFILE",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PUBLIC",
    "LOCALAPPDATA",
    "APPDATA",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "OS",
}

# Substring/regex patterns that must NEVER be passed to child processes
BLOCKED_SECRET_PATTERNS: list[str] = [
    r"(^|_)KEY($|_)",
    r"API[_-]?KEY",
    r"SECRET",
    r"PASSWORD",
    r"(^|_)PASS($|_)",
    r"TOKEN",
    r"CREDENTIAL",
    r"(^|_)AUTH($|_|ENTICATION|ORIZATION)",
    r"DATABASE",
    r"(^|_)DSN($|_)",
    r"PRIVATE[_-]?KEY",
    r"BEARER",
]


@dataclass
class EnvironmentPolicy:
    """Policy for constructing a sanitized environment for subprocess execution."""

    allowed_vars: set[str] = field(default_factory=lambda: set(STANDARD_ALLOWLIST))
    blocked_patterns: list[str] = field(default_factory=lambda: list(BLOCKED_SECRET_PATTERNS))
    custom_env: dict[str, str] = field(default_factory=dict)
    inherit_system_vars: bool = True

    def is_blocked(self, var_name: str) -> bool:
        """Check if a variable name matches any blocked secret pattern."""
        upper_name = var_name.upper()
        return any(re.search(pattern, upper_name) for pattern in self.blocked_patterns)

    def build_env(
        self,
        base_env: dict[str, str] | None = None,
        extra_allowed: set[str] | None = None,
    ) -> dict[str, str]:
        """Build a sanitized environment dictionary.

        Args:
            base_env: Source environment dict (defaults to os.environ).
            extra_allowed: Additional variable names to allowlist for this run.

        Returns:
            dict[str, str]: Sanitized environment safe for subprocess execution.
        """
        source = base_env if base_env is not None else dict(os.environ)
        allowed = set(self.allowed_vars)
        if extra_allowed:
            allowed.update(extra_allowed)

        sanitized: dict[str, str] = {}

        if self.inherit_system_vars:
            # Case-insensitive matching for Windows environment compatibility
            is_windows = os.name == "nt"
            allowed_upper = {v.upper() for v in allowed}

            for key, value in source.items():
                match_key = key.upper() if is_windows else key
                should_allow = match_key in (allowed_upper if is_windows else allowed)

                if should_allow and not self.is_blocked(key):
                    sanitized[key] = value

        # Apply custom environment overrides, ensuring no blocked patterns leak
        for custom_k, custom_v in self.custom_env.items():
            if not self.is_blocked(custom_k):
                sanitized[custom_k] = str(custom_v)

        return sanitized
