"""Architectural verification of the canonical runtime."""

from pathlib import Path

import app.application.agent as agent_pkg
from app.application.agent.orchestrator import MultiAgentOrchestrator
from app.application.agent.runtime import AgentRuntime


def test_canonical_runtime_exports() -> None:
    """Canonical execution engines must be AgentRuntime and MultiAgentOrchestrator."""
    assert hasattr(agent_pkg, "AgentRuntime")
    assert agent_pkg.AgentRuntime is AgentRuntime
    assert MultiAgentOrchestrator is not None

    assert not hasattr(agent_pkg, "DuckDuckGoSearchProvider")
    assert not hasattr(agent_pkg, "HttpxWebFetcher")
    assert not hasattr(agent_pkg, "PlaywrightWebRenderer")


def test_legacy_runtime_is_removed() -> None:
    """Retired graph prototypes must not remain as modules or package exports."""
    agent_dir = Path("app/application/agent")
    for name in ("legacy.py", "graph.py", "nodes.py"):
        assert not (agent_dir / name).exists(), f"{name} must not exist"

    for symbol in ("ByteBuddhiAgent", "create_agent_graph", "AgentNodes", "AgentState", "IntentType"):
        assert not hasattr(agent_pkg, symbol), f"{symbol} must not be exported"
