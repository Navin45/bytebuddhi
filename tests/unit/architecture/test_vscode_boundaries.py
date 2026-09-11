"""VS Code extension must remain a transport client."""

from pathlib import Path

BANNED = (
    "AgentRuntime",
    "MultiAgentOrchestrator",
    "ToolExecutor",
    "ToolPolicyEngine",
    "ProcessManager",
    "WebResearchService",
    "playwright",
    "duckduckgo",
    "child_process",
    "opentelemetry",
    "sqlalchemy",
    "LocalArtifactStore",
)


def test_vscode_extension_does_not_import_runtime_internals() -> None:
    root = Path("vscode-extension/src")
    assert root.exists()
    hits: list[str] = []
    for path in root.rglob("*.ts"):
        if "test" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for token in BANNED:
            if token in text:
                hits.append(f"{path} contains {token}")
    assert hits == []


def test_vscode_extension_has_csp_and_secret_storage() -> None:
    html = Path("vscode-extension/src/views/chatHtml.ts").read_text(encoding="utf-8")
    assert "Content-Security-Policy" in html
    assert "unsafe-inline" not in html
    assert "eval(" not in html
    ext = Path("vscode-extension/src/extension.ts").read_text(encoding="utf-8")
    assert "context.secrets" in ext
    assert "settings.json" not in ext
