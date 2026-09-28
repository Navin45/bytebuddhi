"""Gateway transport must not become a second runtime or leak into domain/application."""

import ast
from pathlib import Path

FORBIDDEN = (
    "app.application.agent.runtime",
    "app.application.agent.orchestrator",
    "app.application.tools.executor",
    "app.application.tools.registry",
    "app.infrastructure.mcp",
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


def test_gateway_client_and_config_do_not_import_the_runtime() -> None:
    root = Path("app/interfaces/gateway")
    violations: list[str] = []
    for name in ("client.py", "config.py", "manager.py", "models.py", "errors.py"):
        for imp in _imports(root / name):
            if any(imp == item or imp.startswith(item + ".") for item in FORBIDDEN):
                violations.append(f"{name} imports {imp}")
    assert not violations, "\n".join(violations)


def test_domain_and_application_do_not_import_the_gateway() -> None:
    violations: list[str] = []
    for folder in (Path("app/domain"), Path("app/application")):
        for path in folder.rglob("*.py"):
            for imp in _imports(path):
                if imp == "app.interfaces.gateway" or imp.startswith("app.interfaces.gateway."):
                    violations.append(f"{path} imports {imp}")
                if imp == "httpx" or imp.startswith("httpx."):
                    violations.append(f"{path} imports {imp}")
    assert not violations, "\n".join(violations)
