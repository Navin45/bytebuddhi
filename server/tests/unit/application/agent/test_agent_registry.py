"""Unit tests for AgentRegistry and AgentDefinition."""

import pytest

from app.application.agent.registry import AgentRegistry, create_default_registry
from app.domain.models.agent import AgentDefinition, AgentRole


def test_agent_registry_registration_and_lookup():
    """Verify registering, retrieving, and checking agents."""
    registry = AgentRegistry()

    definition = AgentDefinition(
        id="custom_agent",
        name="Custom Agent",
        description="A test agent",
        role=AgentRole.RESEARCHER,
        system_prompt="You are a test agent.",
        allowed_capabilities=("read_file",),
        can_delegate=False,
    )

    registry.register(definition)
    assert len(registry) == 1
    assert "custom_agent" in registry
    assert registry.has("custom_agent")

    retrieved = registry.get("custom_agent")
    assert retrieved is not None
    assert retrieved.name == "Custom Agent"
    assert retrieved.role == AgentRole.RESEARCHER
    assert retrieved.allowed_capabilities == ("read_file",)


def test_agent_registry_duplicate_rejection():
    """Verify duplicate IDs are rejected unless allow_override is specified."""
    registry = AgentRegistry()
    defn1 = AgentDefinition(
        id="agent_1",
        name="Agent 1",
        description="First",
        role=AgentRole.CODER,
        system_prompt="Code.",
    )
    defn2 = AgentDefinition(
        id="agent_1",
        name="Agent 1 Duplicate",
        description="Second",
        role=AgentRole.CODER,
        system_prompt="Code again.",
    )

    registry.register(defn1)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(defn2)

    # Allow override
    registry.register(defn2, allow_override=True)
    assert registry.get("agent_1").description == "Second"


def test_agent_registry_empty_id_rejected():
    """Verify empty ID is rejected."""
    registry = AgentRegistry()
    defn = AgentDefinition(
        id="  ",
        name="Empty",
        description="Empty ID",
        role=AgentRole.GENERALIST,
        system_prompt="Prompt",
    )
    with pytest.raises(ValueError, match="cannot be empty"):
        registry.register(defn)


def test_agent_registry_unregistration():
    """Verify unregister removes agent."""
    registry = AgentRegistry()
    defn = AgentDefinition(
        id="temp_agent",
        name="Temp",
        description="Temporary",
        role=AgentRole.TESTER,
        system_prompt="Test.",
    )
    registry.register(defn)
    assert registry.has("temp_agent")

    removed = registry.unregister("temp_agent")
    assert removed is True
    assert not registry.has("temp_agent")
    assert len(registry) == 0

    # Unregistering non-existent returns False
    assert registry.unregister("non_existent") is False


def test_agent_registry_role_filtering():
    """Verify listing agents filtered by role."""
    registry = AgentRegistry()
    registry.register(
        AgentDefinition(id="res1", name="R1", description="desc", role=AgentRole.RESEARCHER, system_prompt="p")
    )
    registry.register(
        AgentDefinition(id="res2", name="R2", description="desc", role=AgentRole.RESEARCHER, system_prompt="p")
    )
    registry.register(
        AgentDefinition(id="coder1", name="C1", description="desc", role=AgentRole.CODER, system_prompt="p")
    )

    researchers = registry.list_agents(role=AgentRole.RESEARCHER)
    assert len(researchers) == 2
    assert {r.id for r in researchers} == {"res1", "res2"}

    coders = registry.list_agents(role=AgentRole.CODER)
    assert len(coders) == 1
    assert coders[0].id == "coder1"

    all_agents = registry.list_agents()
    assert len(all_agents) == 3


def test_default_registry_specialists():
    """Verify standard specialists are pre-configured with safe boundaries."""
    registry = create_default_registry()

    assert len(registry) == 5
    assert registry.has("researcher")
    assert registry.has("coder")
    assert registry.has("reviewer")
    assert registry.has("tester")
    assert registry.has("planner")

    researcher = registry.get("researcher")
    assert researcher is not None
    assert researcher.role == AgentRole.RESEARCHER
    assert researcher.can_delegate is False
    assert researcher.is_mutating is False
    assert "write_file" not in (researcher.allowed_capabilities or ())

    reviewer = registry.get("reviewer")
    assert reviewer is not None
    assert reviewer.role == AgentRole.REVIEWER
    assert reviewer.can_delegate is False
    assert reviewer.is_mutating is False

    coder = registry.get("coder")
    assert coder is not None
    assert coder.role == AgentRole.CODER
    assert coder.is_mutating is True

    planner = registry.get("planner")
    assert planner is not None
    assert planner.role == AgentRole.PLANNER
    assert planner.can_delegate is True
