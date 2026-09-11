from app.application.agent.context import ContextEngine


def test_context_engine_estimate_tokens():
    engine = ContextEngine(avg_chars_per_token=4)
    assert engine.estimate_tokens("") == 0
    assert engine.estimate_tokens("1234") == 1
    assert engine.estimate_tokens("12345678") == 2


def test_context_engine_build_context_basic():
    engine = ContextEngine()
    messages = [
        {"role": "user", "content": "What is 2+2?"},
    ]
    ctx = engine.build_context(system_prompt="You are an assistant.", messages=messages)

    assert len(ctx) == 2
    assert ctx[0]["role"] == "system"
    assert ctx[0]["content"] == "You are an assistant."
    assert ctx[1]["role"] == "user"
    assert ctx[1]["content"] == "What is 2+2?"


def test_context_engine_budget_pruning():
    # Force a very small budget that only fits system + last message
    engine = ContextEngine(max_context_tokens=100)
    messages = [
        {"role": "user", "content": "Old message " * 10},
        {"role": "assistant", "content": "Old response " * 10},
        {"role": "user", "content": "Latest user query"},
    ]

    ctx = engine.build_context(
        system_prompt="Sys prompt",
        messages=messages,
        budget_tokens=40,
    )

    # Must contain system prompt and the latest message, with older ones pruned
    assert ctx[0]["role"] == "system"
    assert ctx[-1]["content"] == "Latest user query"
    assert len(ctx) < len(messages) + 1


def test_context_engine_format_helpers():
    tool_msg = ContextEngine.format_tool_result_message("c1", "echo", "echo output")
    assert tool_msg == {
        "role": "tool",
        "tool_call_id": "c1",
        "name": "echo",
        "content": "echo output",
    }

    asst_msg = ContextEngine.format_assistant_message(
        content="calling tool",
        tool_calls=[{"id": "c1", "name": "echo", "args": {}}],
    )
    assert asst_msg["role"] == "assistant"
    assert asst_msg["content"] == "calling tool"
    assert len(asst_msg["tool_calls"]) == 1
