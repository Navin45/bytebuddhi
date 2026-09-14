from app.infrastructure.llm.message_converter import convert_dict_messages_to_langchain


def test_convert_assistant_tool_calls_translates_arguments_to_args():
    """Internal state stores tool call payloads under "arguments" (see
    app.application.tools.definition.ToolCall and app/application/agent/runtime.py),
    but LangChain's AIMessage requires its ToolCall shape, which uses "args".
    Passing "arguments" through unchanged makes LangChain's pydantic validation call
    langchain_core.messages.tool.tool_call(...) with an unexpected "arguments" kwarg,
    raising a TypeError on the second turn of any tool-calling conversation.
    """
    messages = [
        {"role": "user", "content": "What is the weather in Paris?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "name": "get_weather", "arguments": {"city": "Paris"}},
            ],
        },
        {"role": "tool", "content": '{"temp_c": 18}', "tool_call_id": "call_1"},
    ]

    lc_messages = convert_dict_messages_to_langchain(messages)

    assistant_message = lc_messages[1]
    assert assistant_message.tool_calls == [
        {"id": "call_1", "name": "get_weather", "args": {"city": "Paris"}, "type": "tool_call"},
    ]
