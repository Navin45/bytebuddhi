"""ModelContext domain model for structured LLM invocation context."""

from dataclasses import dataclass, field
from typing import Any

from app.domain.models.memory import ExecutionObservation, MemoryItem


@dataclass
class ModelContext:
    """Structured internal context representation before converting to model-specific messages."""

    system_prompt: str
    messages: list[dict[str, Any]]
    task: str | None = None
    memories: list[MemoryItem] = field(default_factory=list)
    code_context: list[dict[str, Any]] = field(default_factory=list)
    observations: list[ExecutionObservation] = field(default_factory=list)
    tool_definitions: list[dict[str, Any]] = field(default_factory=list)
    artifact_references: list[dict[str, Any]] = field(default_factory=list)
    estimated_tokens: int = 0
    truncated_sections: list[str] = field(default_factory=list)

    def to_model_messages(self) -> list[dict[str, Any]]:
        """Convert structured context components into an ordered list of model message dicts."""
        # 1. Enrich system prompt with memory, code context, observations, and artifact references
        system_sections = [self.system_prompt]

        if self.memories:
            mem_lines = ["\n[RELEVANT MEMORIES]"]
            for m in self.memories:
                mem_lines.append(f"- ({m.memory_type.value}) {m.content}")
            system_sections.append("\n".join(mem_lines))

        if self.code_context:
            code_lines = ["\n[RELEVANT CODE CONTEXT]"]
            for cc in self.code_context:
                path = cc.get("file_path", "unknown")
                snippet = cc.get("snippet", "")
                code_lines.append(f"File: {path}\n```\n{snippet}\n```")
            system_sections.append("\n".join(code_lines))

        if self.artifact_references:
            art_lines = ["\n[PERSISTED ARTIFACT REFERENCES]"]
            for art in self.artifact_references:
                art_id = art.get("artifact_id", "")
                summary = art.get("summary", "")
                preview = art.get("preview", "")
                ref_text = f"- Artifact ID: {art_id} | Summary: {summary}"
                if preview:
                    ref_text += f"\n  Preview: {preview}"
                art_lines.append(ref_text)
            system_sections.append("\n".join(art_lines))

        if self.observations:
            obs_lines = ["\n[RECENT EXECUTION OBSERVATIONS]"]
            for obs in self.observations:
                status = "failed" if obs.is_error else "succeeded"
                obs_lines.append(f"- Tool '{obs.tool_name}' ({status}, exit {obs.exit_code}): {obs.summary}")
            system_sections.append("\n".join(obs_lines))

        combined_system = "\n\n".join(system_sections)

        system_message = {"role": "system", "content": combined_system}
        return [system_message, *self.messages]
