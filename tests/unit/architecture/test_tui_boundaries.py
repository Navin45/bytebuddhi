"""The terminal client is a gateway client, not another agent runtime."""

import ast
from pathlib import Path

TUI_DIR = Path("app/interfaces/tui").resolve()

FORBIDDEN_PREFIXES = (
    "sqlalchemy",
    "redis",
    "asyncpg",
    "app.application.agent.runtime",
    "app.application.agent.orchestrator",
    "app.application.use_cases.agent.execute_task",
    "app.application.llm",
    "app.infrastructure.persistence",
    "app.infrastructure.llm",
)

FORBIDDEN_TOKENS = (
    "AgentRuntime(",
    "ExecuteTaskUseCase(",
    "MultiAgentOrchestrator(",
    "create_async_engine(",
    "Redis(",
)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def test_tui_does_not_import_runtime_database_or_redis() -> None:
    violations: list[str] = []
    for py_file in TUI_DIR.rglob("*.py"):
        for imp in _imports(py_file):
            if any(imp == prefix or imp.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES):
                violations.append(f"{py_file.relative_to(TUI_DIR)} imports {imp}")
        text = py_file.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if token in text:
                violations.append(f"{py_file.relative_to(TUI_DIR)} contains {token}")
    assert not violations, "TUI crossed the gateway boundary:\n" + "\n".join(violations)
