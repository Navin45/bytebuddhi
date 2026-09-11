"""Architectural verification of canonical runtime and legacy prototype quarantine."""

import pytest

import app.application.agent as agent_pkg
from app.application.agent.legacy import ByteBuddhiAgent, create_agent_graph
from app.application.agent.orchestrator import MultiAgentOrchestrator
from app.application.agent.runtime import AgentRuntime


def test_canonical_runtime_exports() -> None:
    """Canonical execution engines must be AgentRuntime and MultiAgentOrchestrator."""
    assert hasattr(agent_pkg, "AgentRuntime")
    assert agent_pkg.AgentRuntime is AgentRuntime
    assert MultiAgentOrchestrator is not None

    # Infrastructure services must never be exported from agent package
    assert not hasattr(agent_pkg, "TavilySearchService")


def test_legacy_runtime_deprecation_warning() -> None:
    """Instantiating legacy prototypes must emit DeprecationWarning."""
    from unittest.mock import MagicMock

    mock_llm = MagicMock()

    with pytest.deprecated_call():
        create_agent_graph(mock_llm)

    with pytest.deprecated_call():
        ByteBuddhiAgent(mock_llm)
