"""ContextEngine for ByteBuddhi Agent Runtime.

Constructs, formats, and budgets model context before LLM invocations using
a priority-based budgeting pipeline and structured ModelContext.
"""

from typing import Any

from app.application.ports.output.logger import get_logger
from app.domain.models.artifact import Artifact
from app.domain.models.context import ModelContext
from app.domain.models.memory import ExecutionObservation, MemoryItem
from app.domain.services.conversation_context_service import ConversationContextService

logger = get_logger(__name__)

# Re-export ModelContext for backward compatibility
__all__ = ["ContextEngine", "ModelContext"]


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
        """Estimate token count using canonical ConversationContextService or character ratio."""
        if not text:
            return 0
        ratio = getattr(self, "avg_chars_per_token", 4)
        if ratio == 4:
            return ConversationContextService.estimate_token_count(text)
        return len(text) // ratio

    def estimate_message_tokens(self, message: dict[str, Any]) -> int:
        """Estimate token count for a message dict."""
        content = message.get("content") or ""
        tokens = self.estimate_tokens(str(content))
        # Overhead for role and framing
        tokens += 4
        if message.get("tool_calls"):
            tokens += self.estimate_tokens(str(message["tool_calls"]))
        return tokens

    def build_model_context(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        memories: list[MemoryItem] | None = None,
        code_context: list[dict[str, Any]] | None = None,
        observations: list[ExecutionObservation] | None = None,
        tool_definitions: list[dict[str, Any]] | None = None,
        artifacts: list[Artifact | dict[str, Any]] | None = None,
        task: str | None = None,
        budget_tokens: int | None = None,
    ) -> ModelContext:
        """Construct the prioritized, budgeted ModelContext for model invocation.

        Priority Hierarchy:
          1. System instructions (Unprunable)
          2. Current task / latest user message (Unprunable)
          3. Tool definitions (Reserved allowance)
          4. Essential tool observations (High priority)
          5. Curated memories & code context (Medium priority)
          6. Conversation history (Lowest priority, pruned oldest-first)
        """
        max_budget = budget_tokens if budget_tokens is not None else self.max_context_tokens
        truncated_sections: list[str] = []

        # 1. Unprunable anchors: System prompt and latest message
        system_base_tokens = self.estimate_tokens(system_prompt) + 4
        last_msg = messages[-1] if messages else None
        last_msg_tokens = self.estimate_message_tokens(last_msg) if last_msg else 0
        anchor_tokens = system_base_tokens + last_msg_tokens

        # Check for unprunable anchor overflow
        if anchor_tokens > max_budget:
            truncated_sections.append("budget_overflow")
            if len(messages) > 1:
                truncated_sections.append("conversation_history")
            if observations:
                truncated_sections.append("observations")
            if memories:
                truncated_sections.append("memories")
            if code_context:
                truncated_sections.append("code_context")
            if artifacts:
                truncated_sections.append("artifacts")

            selected_messages = [last_msg] if last_msg else []
            ctx = ModelContext(
                system_prompt=system_prompt,
                messages=selected_messages,
                task=task,
                memories=[],
                code_context=[],
                observations=[],
                tool_definitions=tool_definitions or [],
                artifact_references=[],
                estimated_tokens=0,
                truncated_sections=sorted(list(set(truncated_sections))),
            )
            final_msgs = ctx.to_model_messages()
            ctx.estimated_tokens = sum(self.estimate_message_tokens(m) for m in final_msgs)
            return ctx

        remaining_budget = max_budget - anchor_tokens

        # 2. Tool definitions reserved allowance (~50 tokens per tool)
        tool_overhead = (len(tool_definitions) * 50) if tool_definitions else 0
        reserved_tool_tokens = min(tool_overhead, remaining_budget)
        remaining_budget -= reserved_tool_tokens

        # 3. Essential tool observations (High priority, cap = min(15% of max_budget, remaining_budget))
        obs_to_include: list[ExecutionObservation] = []
        if observations:
            obs_cap = min(int(max_budget * 0.15), remaining_budget)
            obs_tokens_used = 0
            for obs in reversed(observations):
                status = "failed" if obs.is_error else "succeeded"
                line = f"- Tool '{obs.tool_name}' ({status}, exit {obs.exit_code}): {obs.summary}"
                cost = self.estimate_tokens(line) + 2
                if obs_tokens_used + cost <= obs_cap and remaining_budget - cost >= 0:
                    obs_to_include.append(obs)
                    obs_tokens_used += cost
                    remaining_budget -= cost
                else:
                    truncated_sections.append("observations")
                    break
            obs_to_include.reverse()

        # 4. Curated memories (Medium priority, cap = min(20% of max_budget, remaining_budget))
        memories_to_include: list[MemoryItem] = []
        if memories:
            mem_cap = min(int(max_budget * 0.20), remaining_budget)
            mem_tokens_used = 0
            for mem in memories:
                line = f"- ({mem.memory_type.value}) {mem.content}"
                cost = self.estimate_tokens(line) + 2
                if mem_tokens_used + cost <= mem_cap and remaining_budget - cost >= 0:
                    memories_to_include.append(mem)
                    mem_tokens_used += cost
                    remaining_budget -= cost
                else:
                    truncated_sections.append("memories")
                    break

        # 5. Code context (Medium priority, cap = min(20% of max_budget, remaining_budget))
        code_to_include: list[dict[str, Any]] = []
        if code_context:
            code_cap = min(int(max_budget * 0.20), remaining_budget)
            code_tokens_used = 0
            for cc in code_context:
                path = cc.get("file_path", "unknown")
                snippet = cc.get("snippet", "")
                text = f"File: {path}\n```\n{snippet}\n```"
                cost = self.estimate_tokens(text) + 2
                if code_tokens_used + cost <= code_cap and remaining_budget - cost >= 0:
                    code_to_include.append(cc)
                    code_tokens_used += cost
                    remaining_budget -= cost
                else:
                    truncated_sections.append("code_context")
                    break

        # 6. Artifact references (Budgeted, cap = min(10% of max_budget, remaining_budget))
        art_dicts: list[dict[str, Any]] = []
        if artifacts:
            art_cap = min(int(max_budget * 0.10), remaining_budget)
            art_tokens_used = 0
            for a in artifacts:
                ad = a.to_context_dict() if isinstance(a, Artifact) else a
                art_id = ad.get("artifact_id", "")
                summary = ad.get("summary", "")
                preview = ad.get("preview", "")
                ref_text = f"- Artifact ID: {art_id} | Summary: {summary}"
                if preview:
                    ref_text += f"\n  Preview: {preview}"
                cost = self.estimate_tokens(ref_text) + 2
                if art_tokens_used + cost <= art_cap and remaining_budget - cost >= 0:
                    art_dicts.append(ad)
                    art_tokens_used += cost
                    remaining_budget -= cost
                else:
                    truncated_sections.append("artifacts")
                    break

        # 7. Conversation history (Lowest priority, oldest pruned first)
        older_messages: list[dict[str, Any]] = []
        if messages and len(messages) > 1:
            for msg in reversed(messages[:-1]):
                msg_tokens = self.estimate_message_tokens(msg)
                if remaining_budget - msg_tokens >= 0:
                    older_messages.append(msg)
                    remaining_budget -= msg_tokens
                else:
                    truncated_sections.append("conversation_history")
                    break

        selected_messages = [*reversed(older_messages)]
        if last_msg:
            selected_messages.append(last_msg)

        ctx = ModelContext(
            system_prompt=system_prompt,
            messages=selected_messages,
            task=task,
            memories=memories_to_include,
            code_context=code_to_include,
            observations=obs_to_include,
            tool_definitions=tool_definitions or [],
            artifact_references=art_dicts,
            estimated_tokens=0,
            truncated_sections=sorted(list(set(truncated_sections))),
        )

        # Recalculate exact estimated tokens from actual model payload + reserved tool overhead
        final_messages = ctx.to_model_messages()
        actual_tokens = sum(self.estimate_message_tokens(m) for m in final_messages) + reserved_tool_tokens
        ctx.estimated_tokens = actual_tokens
        return ctx

    def build_context(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        budget_tokens: int | None = None,
        memories: list[MemoryItem] | None = None,
        code_context: list[dict[str, Any]] | None = None,
        observations: list[ExecutionObservation] | None = None,
        artifacts: list[Artifact | dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Backwards-compatible convenience wrapper returning list of model message dicts."""
        ctx = self.build_model_context(
            system_prompt=system_prompt,
            messages=messages,
            tool_definitions=tools,
            budget_tokens=budget_tokens,
            memories=memories,
            code_context=code_context,
            observations=observations,
            artifacts=artifacts,
        )
        return ctx.to_model_messages()

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
