"""Utility for converting dictionary messages to LangChain message instances."""

from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)


def convert_dict_messages_to_langchain(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    """Convert raw message dicts to LangChain BaseMessage objects.

    Supports 'system', 'user', 'assistant', and 'tool' roles.
    """
    lc_messages: list[BaseMessage] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            lc_messages.append(SystemMessage(content=content))
        elif role == "assistant":
            # If tool calls were stored in the message dict. Internal state stores the
            # tool call payload under "arguments" (see app.application.tools.definition.ToolCall),
            # but LangChain's AIMessage expects the LangChain ToolCall shape, which uses "args".
            tool_calls = [
                {
                    "id": tc.get("id", ""),
                    "name": tc.get("name", ""),
                    "args": tc.get("args", tc.get("arguments", {})),
                    "type": "tool_call",
                }
                for tc in msg.get("tool_calls", [])
            ]
            lc_messages.append(AIMessage(content=content or "", tool_calls=tool_calls))
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            lc_messages.append(ToolMessage(content=content, tool_call_id=tool_call_id))
        else:
            lc_messages.append(HumanMessage(content=content))

    return lc_messages
