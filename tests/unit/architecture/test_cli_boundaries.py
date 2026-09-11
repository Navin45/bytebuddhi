"""CLI architecture: thin adapter over use cases, not a second runtime."""

import ast
from pathlib import Path

CLI_DIR = Path("app/interfaces/cli").resolve()
COMPOSITION_ROOTS = {"bootstrap.py"}

FORBIDDEN_PREFIXES = (
    "app.application.agent.runtime",
    "app.application.agent.orchestrator",
    "app.application.tools.executor",
    "app.application.policy.tool_policy",
    "app.application.workspace.resolution_service",
    "app.infrastructure.web.search",
    "app.infrastructure.web.render",
    "app.infrastructure.execution.local_process_manager",
    "app.infrastructure.storage.local_artifact_store",
    "app.infrastructure.persistence.postgres.repositories",
    "app.infrastructure.persistence.postgres.checkpoint_saver",
    "opentelemetry.sdk",
    "playwright",
    "fastapi",
    "starlette",
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


def test_cli_command_modules_do_not_import_runtime_or_infra_adapters() -> None:
    violations: list[str] = []
    for py_file in CLI_DIR.glob("*.py"):
        if py_file.name in COMPOSITION_ROOTS or py_file.name == "__init__.py":
            continue
        for imp in _imports(py_file):
            if any(imp == prefix or imp.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES):
                violations.append(f"{py_file.name} imports {imp}")
            if "duckduckgo" in imp.lower():
                violations.append(f"{py_file.name} imports {imp}")
    assert not violations, "CLI adapter imported forbidden modules:\n" + "\n".join(violations)


def test_cli_does_not_implement_an_agent_loop() -> None:
    banned_tokens = (
        "ToolExecutor(",
        "AgentRuntime(",
        "MultiAgentOrchestrator(",
        "create_llm_provider",
        "LocalProcessManager(",
    )
    hits: list[str] = []
    for py_file in CLI_DIR.glob("*.py"):
        if py_file.name in COMPOSITION_ROOTS:
            continue
        text = py_file.read_text(encoding="utf-8")
        for token in banned_tokens:
            if token in text:
                hits.append(f"{py_file.name} contains {token}")
    assert not hits, "CLI contains runtime construction:\n" + "\n".join(hits)
