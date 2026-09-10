"""ContextEngine for ByteBuddhi Agent Runtime.

Constructs, formats, and budgets model context before LLM invocations.
"""

from typing import Any

from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class ContextEngine:
    """Constructs prompt and message contexts for LLM calls with budget enforcement."""

    def __init__(
        self,
        max_context_tokens: int = 8000,
        avg_chars_per_token: int = 4,
    ):
        self.max_context_tokens = max_context_tokens
        self.avg_chars_per_token = avg_chars_per_token

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count based on character length."""
        if not text:
            return 0
        return max(1, len(text) // self.avg_chars_per_token)

    def estimate_message_tokens(self, message: dict[str, Any]) -> int:
        """Estimate token count for a message dict."""
        content = message.get("content") or ""
        tokens = self.estimate_tokens(str(content))
        # Account for role and metadata overhead
        tokens += 4
        if message.get("tool_calls"):
            tokens += self.estimate_tokens(str(message["tool_calls"]))
        return tokens

    def build_context(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        budget_tokens: int | None = None,
    ) -> list[dict[str, Any]]:
        """Construct the budgeted message list for the model invocation.

        Args:
            system_prompt: System/developer instructions.
            messages: Conversation turns and tool results.
            tools: Optional tool schemas (used for budget estimation).
            budget_tokens: Max allowed tokens (defaults to self.max_context_tokens).

        Returns:
            list[dict[str, Any]]: Ordered message dicts conforming to model budget.
        """
        max_budget = budget_tokens if budget_tokens is not None else self.max_context_tokens

        # Reserve budget for tools schema overhead if tools present (~50 tokens per tool)
        tool_overhead = (len(tools) * 50) if tools else 0
        available_budget = max_budget - tool_overhead

        # System message is mandatory
        system_msg = {"role": "system", "content": system_prompt}
        system_tokens = self.estimate_message_tokens(system_msg)
        remaining_budget = available_budget - system_tokens

        if not messages:
            return [system_msg]

        # Prioritize recent messages: select from newest backwards
        selected_messages: list[dict[str, Any]] = []
        # Always include the last message
        last_msg = messages[-1]
        last_msg_tokens = self.estimate_message_tokens(last_msg)
        selected_messages.append(last_msg)
        remaining_budget -= last_msg_tokens

        # Add earlier messages in reverse order until budget is exhausted
        for msg in reversed(messages[:-1]):
            msg_tokens = self.estimate_message_tokens(msg)
            if remaining_budget - msg_tokens >= 0:
                selected_messages.append(msg)
                remaining_budget -= msg_tokens
            else:
                logger.info(
                    "Context budget reached, pruning older messages",
                    pruned_at=msg.get("role"),
                )
                break

        # Restore chronological order
        selected_messages.reverse()

        return [system_msg, *selected_messages]

    @staticmethod
    def format_tool_result_message(
        tool_call_id: str,
        tool_name: str,
        content: str,
    ) -> dict[str, Any]:
        """Format a tool execution result into a model-compatible message dict."""
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": content,
        }

    @staticmethod
    def format_assistant_message(
        content: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Format an assistant turn into a model-compatible message dict."""
        msg: dict[str, Any] = {
            "role": "assistant",
            "content": content or "",
        }
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return msg
