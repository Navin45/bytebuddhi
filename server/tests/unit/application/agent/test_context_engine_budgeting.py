"""Unit tests for ContextEngine refactor and priority budgeting."""

from app.application.agent.context import ContextEngine
from app.domain.models.artifact import Artifact
from app.domain.models.memory import (
    ExecutionObservation,
    MemoryItem,
    MemoryScope,
    MemoryType,
)


def test_build_model_context_basic():
    engine = ContextEngine(max_context_tokens=4000)

    messages = [
        {"role": "user", "content": "How do I run tests?"},
        {"role": "assistant", "content": "Use pytest."},
        {"role": "user", "content": "What about ruff?"},
    ]

    ctx = engine.build_model_context(
        system_prompt="You are ByteBuddhi.",
        messages=messages,
    )

    assert ctx.system_prompt == "You are ByteBuddhi."
    assert len(ctx.messages) == 3
    assert ctx.estimated_tokens > 0

    model_msgs = ctx.to_model_messages()
    assert model_msgs[0]["role"] == "system"
    assert "You are ByteBuddhi." in model_msgs[0]["content"]
    assert model_msgs[-1]["content"] == "What about ruff?"


def test_enrichment_with_memories_and_artifacts():
    engine = ContextEngine()

    mem = MemoryItem.create(
        scope=MemoryScope.USER,
        scope_id="u1",
        memory_type=MemoryType.USER_PREFERENCE,
        content="Prefer pytest over unittest",
    )

    obs = ExecutionObservation.create(
        run_id="r1",
        tool_name="run_command",
        tool_call_id="tc_1",
        summary="Tests executed successfully",
        exit_code=0,
    )

    art = Artifact.create(
        artifact_type="command_stdout",
        size_bytes=100000,
        storage_ref="storage/artifacts/log.txt",
        summary="Command output log",
    )

    ctx = engine.build_model_context(
        system_prompt="Base prompt.",
        messages=[{"role": "user", "content": "Check status."}],
        memories=[mem],
        observations=[obs],
        artifacts=[art],
    )

    model_msgs = ctx.to_model_messages()
    system_content = model_msgs[0]["content"]

    assert "[RELEVANT MEMORIES]" in system_content
    assert "Prefer pytest over unittest" in system_content
    assert "[RECENT EXECUTION OBSERVATIONS]" in system_content
    assert "Tests executed successfully" in system_content
    assert "[PERSISTED ARTIFACT REFERENCES]" in system_content
    assert "Command output log" in system_content


def test_budget_pruning_preserves_system_and_last_message():
    # Very small budget (e.g. 50 tokens)
    engine = ContextEngine(max_context_tokens=60)

    messages = [
        {"role": "user", "content": "Old message 1 " * 10},
        {"role": "assistant", "content": "Old reply 1 " * 10},
        {"role": "user", "content": "Latest critical request"},
    ]

    ctx = engine.build_model_context(
        system_prompt="Short prompt.",
        messages=messages,
        budget_tokens=25,
    )

    # Older messages should be pruned, but system and latest message MUST be kept
    assert len(ctx.messages) == 1
    assert ctx.messages[0]["content"] == "Latest critical request"
    assert "conversation_history" in ctx.truncated_sections


def test_all_sections_large_simultaneously_strictly_bounded():
    """Verify that when all sections are simultaneously large, final tokens strictly <= budget."""
    engine = ContextEngine()
    budget = 400

    system_prompt = "You are ByteBuddhi assistant."  # ~6 tokens
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"Turn {i} " * 20} for i in range(20)]
    tools = [{"name": f"tool_{i}", "description": "desc"} for i in range(5)]  # ~250 tokens reserved
    observations = [
        ExecutionObservation.create(
            run_id="r1",
            tool_name=f"cmd_{i}",
            tool_call_id=f"c_{i}",
            summary=f"Huge execution observation result summary {i} " * 10,
        )
        for i in range(10)
    ]
    memories = [
        MemoryItem.create(
            scope=MemoryScope.USER,
            scope_id="u1",
            memory_type=MemoryType.USER_PREFERENCE,
            content=f"Important user preference rule {i} " * 10,
        )
        for i in range(10)
    ]
    code_context = [{"file_path": f"src/mod_{i}.py", "snippet": "def func(): pass\n" * 20} for i in range(5)]
    artifacts = [
        Artifact.create(
            artifact_type="log",
            size_bytes=10000,
            storage_ref=f"log_{i}.txt",
            summary=f"Summary of log {i}",
            preview=f"Long preview text {i} " * 20,
        )
        for i in range(5)
    ]

    ctx = engine.build_model_context(
        system_prompt=system_prompt,
        messages=messages,
        tool_definitions=tools,
        observations=observations,
        memories=memories,
        code_context=code_context,
        artifacts=artifacts,
        budget_tokens=budget,
    )

    # Invariant: final estimated tokens MUST be <= budget
    assert ctx.estimated_tokens <= budget

    # Final payload check: message tokens + reserved tools overhead == estimated_tokens
    final_msgs = ctx.to_model_messages()
    payload_tokens = sum(engine.estimate_message_tokens(m) for m in final_msgs)
    assert payload_tokens <= budget
    assert ctx.estimated_tokens == payload_tokens + min(len(tools) * 50, budget)

    # Must contain truncation flags
    assert len(ctx.truncated_sections) > 0


def test_unprunable_anchor_overflow_reported_explicitly():
    """Verify that if system prompt + last message exceeds budget, overflow is exposed without false clamping."""
    engine = ContextEngine()

    big_system = "System rule " * 100  # ~300 tokens
    big_last_msg = {"role": "user", "content": "User input " * 100}  # ~300 tokens

    ctx = engine.build_model_context(
        system_prompt=big_system,
        messages=[big_last_msg],
        budget_tokens=100,  # Far smaller than anchors
    )

    # Overflow is marked
    assert "budget_overflow" in ctx.truncated_sections
    # Anchors are preserved
    assert len(ctx.messages) == 1
    assert "User input" in ctx.messages[0]["content"]
    # Reported token count accurately reflects payload, not clamped to 100
    assert ctx.estimated_tokens > 100


def test_artifact_previews_budgeted():
    """Verify that artifact previews are accounted for in token budget."""
    engine = ContextEngine()

    art = Artifact.create(
        artifact_type="command_stdout",
        size_bytes=50000,
        storage_ref="storage/huge.log",
        summary="Command build log",
        preview="Compiling module A... done\n" * 50,
    )

    ctx = engine.build_model_context(
        system_prompt="Base prompt.",
        messages=[{"role": "user", "content": "Status?"}],
        artifacts=[art],
        budget_tokens=50,  # Small budget: cannot fit large preview
    )

    # Artifact preview was truncated/omitted to respect the 50 token budget
    assert ctx.estimated_tokens <= 50
    assert "artifacts" in ctx.truncated_sections
    assert len(ctx.artifact_references) == 0
