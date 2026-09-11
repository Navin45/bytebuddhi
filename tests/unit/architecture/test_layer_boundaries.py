"""Architectural layer boundary enforcement tests using AST import analysis."""

import ast
from pathlib import Path


def _get_imports(file_path: Path) -> list[str]:
    """Parse a python file with AST and return all top-level imported module paths."""
    imports = []
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    except Exception as e:
        raise RuntimeError(f"Failed to parse {file_path}: {e}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def test_domain_layer_purity() -> None:
    """Domain layer must not depend on Application, Infrastructure, or web frameworks."""
    domain_dir = Path("app/domain").resolve()
    assert domain_dir.exists()

    violations = []
    for py_file in domain_dir.rglob("*.py"):
        imports = _get_imports(py_file)
        for imp in imports:
            if imp.startswith("app.application"):
                violations.append(f"{py_file.name} imports application: {imp}")
            elif imp.startswith("app.infrastructure"):
                violations.append(f"{py_file.name} imports infrastructure: {imp}")
            elif imp.startswith("fastapi") or imp.startswith("starlette"):
                violations.append(f"{py_file.name} imports web framework: {imp}")

    assert not violations, "Domain boundary violations detected:\n" + "\n".join(violations)


def test_application_layer_purity() -> None:
    """Application layer must not depend directly on concrete Infrastructure or web frameworks."""
    app_dir = Path("app/application").resolve()
    assert app_dir.exists()

    violations = []
    for py_file in app_dir.rglob("*.py"):
        imports = _get_imports(py_file)
        for imp in imports:
            if imp.startswith("app.infrastructure"):
                violations.append(f"{py_file.name} imports infrastructure: {imp}")
            elif imp.startswith("fastapi") or imp.startswith("starlette"):
                violations.append(f"{py_file.name} imports web framework: {imp}")

    assert not violations, "Application boundary violations detected:\n" + "\n".join(violations)


def test_api_routes_do_not_own_runtime_execution() -> None:
    """HTTP routes may depend on ExecuteTaskUseCase, not AgentRuntime or MultiAgentOrchestrator."""
    routes_dir = Path("app/interfaces/api/routes").resolve()
    violations = []
    for py_file in routes_dir.rglob("*.py"):
        imports = _get_imports(py_file)
        for imp in imports:
            if imp in {
                "app.application.agent.runtime",
                "app.application.agent.orchestrator",
            }:
                violations.append(f"{py_file.name} imports {imp}")
    assert not violations, "API runtime-ownership violations:\n" + "\n".join(violations)


def test_cli_adapters_do_not_import_agent_runtime() -> None:
    """CLI command modules may not own AgentRuntime; bootstrap is the composition root."""
    cli_dir = Path("app/interfaces/cli").resolve()
    violations = []
    for py_file in cli_dir.rglob("*.py"):
        if py_file.name == "bootstrap.py":
            continue
        imports = _get_imports(py_file)
        for imp in imports:
            if imp in {
                "app.application.agent.runtime",
                "app.application.agent.orchestrator",
            }:
                violations.append(f"{py_file.name} imports {imp}")
    assert not violations, "CLI runtime-ownership violations:\n" + "\n".join(violations)
