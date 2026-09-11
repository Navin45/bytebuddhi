"""Architecture tests: application web code depends on ports, not adapters."""

import ast
from pathlib import Path

_APP_WEB = Path("app/application")
_FORBIDDEN_MODULES = (
    "playwright",
    "aiohttp",
    "bs4",
    "beautifulsoup4",
    "duckduckgo",
    "ddgs",
    "httpx",
)
_FORBIDDEN_NAMES = (
    "DuckDuckGoSearchProvider",
    "HttpxWebFetcher",
    "PlaywrightWebRenderer",
    "BeautifulSoup",
    "async_playwright",
)


def _imports_and_names(file_path: Path) -> tuple[list[str], list[str]]:
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    imports: list[str] = []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
                names.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
            names.append(node.module.split(".")[0])
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
    return imports, names


def test_application_web_depends_on_ports_not_adapters() -> None:
    violations: list[str] = []
    for py_file in _APP_WEB.rglob("*.py"):
        imports, names = _imports_and_names(py_file)
        for imp in imports:
            lowered = imp.lower()
            for forbidden in _FORBIDDEN_MODULES:
                if lowered == forbidden or lowered.startswith(forbidden + "."):
                    violations.append(f"{py_file} imports {imp}")
            if "infrastructure.web" in imp:
                violations.append(f"{py_file} imports infrastructure adapter: {imp}")
        for name in names:
            if name in _FORBIDDEN_NAMES:
                violations.append(f"{py_file} references {name}")
    assert not violations, "Application layer leaked infrastructure web types:\n" + "\n".join(violations)


def test_application_uses_web_ports() -> None:
    search = Path("app/application/ports/output/web/search.py").read_text(encoding="utf-8")
    fetch = Path("app/application/ports/output/web/fetch.py").read_text(encoding="utf-8")
    render = Path("app/application/ports/output/web/render.py").read_text(encoding="utf-8")
    assert "class WebSearchProvider" in search
    assert "class WebFetcher" in fetch
    assert "class WebRenderer" in render
    service = Path("app/application/web/research_service.py").read_text(encoding="utf-8")
    assert "WebSearchProvider" in service
    assert "WebFetcher" in service
    assert "WebRenderer" in service


def test_runtime_has_no_web_research_special_case() -> None:
    runtime = Path("app/application/agent/runtime.py").read_text(encoding="utf-8")
    assert 'tool_name == "web_research"' not in runtime
    assert "web_research" not in runtime
