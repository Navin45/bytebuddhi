"""Provider SDKs must stay behind infrastructure adapters."""

import ast
from pathlib import Path

FORBIDDEN = (
    "openai",
    "anthropic",
    "langchain_openai",
    "langchain_anthropic",
    "google.generativeai",
    "boto3",
    "cohere",
    "groq",
    "mistralai",
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


def _is_forbidden(module: str) -> bool:
    root = module.split(".")[0]
    return root in FORBIDDEN or module in FORBIDDEN


def test_domain_and_application_do_not_import_provider_sdks() -> None:
    violations: list[str] = []
    for folder in (Path("app/domain"), Path("app/application")):
        for py_file in folder.rglob("*.py"):
            for imp in _imports(py_file):
                if _is_forbidden(imp):
                    violations.append(f"{py_file} imports {imp}")
    assert not violations, "Provider SDK leaked into domain/application:\n" + "\n".join(violations)


def test_agent_runtime_does_not_import_provider_sdks() -> None:
    path = Path("app/application/agent/runtime.py")
    hits = [imp for imp in _imports(path) if _is_forbidden(imp)]
    assert hits == []
