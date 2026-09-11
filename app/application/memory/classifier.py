"""Deterministic memory classification layer for ByteBuddhi."""

import re
from dataclasses import dataclass
from enum import StrEnum

from app.domain.models.memory import MemoryScope, MemoryType


class ClassificationAction(StrEnum):
    """Action to take on classified memory."""

    PERSIST_WORKING = "persist_working"
    PERSIST_DURABLE = "persist_durable"
    DISCARD = "discard"


@dataclass
class ClassificationResult:
    """Outcome of classifying a candidate memory."""

    action: ClassificationAction
    memory_type: MemoryType
    importance: float
    reason: str


class MemoryClassifier:
    """Classifies input information deterministically without requiring an LLM."""

    # Patterns indicating user preferences or long-term rules
    USER_PREFERENCE_PATTERNS: list[str] = [
        r"\bi\s+(?:prefer|like|want|always\s+use|never\s+use)\b",
        r"\bmy\s+preference\b",
        r"\bplease\s+(?:always|never)\b",
        r"\bformat\s+(?:as|using)\b",
        r"\bdo\s+not\s+(?:use|import|call)\b",
    ]

    # Patterns indicating project-level facts or conventions
    PROJECT_PATTERNS: list[str] = [
        r"\b(?:project|repository|repo)\s+(?:convention|structure|standard|rule)\b",
        r"\bwe\s+use\s+(?:python|uv|fastapi|postgres|redis|docker)\b",
        r"\barchitecture\s+(?:is|uses|follows)\b",
        r"\bbuild\s+command\b",
        r"\bdatabase\s+(?:schema|migration)\b",
    ]

    # Noise and discard patterns
    DISCARD_PATTERNS: list[str] = [
        r"^(?:ok|okay|yes|no|thanks|thank\s+you|hello|hi|done)[\.!]?$",
        r"^\s*$",
    ]

    def classify(
        self,
        content: str,
        source: str = "user",
        scope: MemoryScope | None = None,
        hint_type: MemoryType | None = None,
    ) -> ClassificationResult:
        """Classify content deterministically into working, durable, or discard."""
        clean = content.strip()

        # 1. Trivial length or pure noise -> DISCARD
        default_type = (
            MemoryType.PROJECT
            if scope == MemoryScope.PROJECT
            else (
                MemoryType.WORKING
                if scope in (MemoryScope.AGENT_RUN, MemoryScope.CONVERSATION)
                else MemoryType.USER_PREFERENCE
            )
        )

        if len(clean) < 4:
            return ClassificationResult(
                action=ClassificationAction.DISCARD,
                memory_type=default_type,
                importance=0.0,
                reason="Content too short to retain",
            )

        clean_lower = clean.lower()
        for pat in self.DISCARD_PATTERNS:
            if re.match(pat, clean_lower):
                return ClassificationResult(
                    action=ClassificationAction.DISCARD,
                    memory_type=default_type,
                    importance=0.0,
                    reason="Content matches discard pattern",
                )

        # 2. If caller provided an explicit hint, respect it if valid for scope
        if hint_type == MemoryType.USER_PREFERENCE and (scope is None or scope == MemoryScope.USER):
            return ClassificationResult(
                action=ClassificationAction.PERSIST_DURABLE,
                memory_type=MemoryType.USER_PREFERENCE,
                importance=0.8,
                reason="Explicitly tagged as user preference",
            )
        if hint_type == MemoryType.PROJECT and (scope is None or scope == MemoryScope.PROJECT):
            return ClassificationResult(
                action=ClassificationAction.PERSIST_DURABLE,
                memory_type=MemoryType.PROJECT,
                importance=0.7,
                reason="Explicitly tagged as project fact",
            )
        if hint_type == MemoryType.LONG_TERM and (scope is None or scope in (MemoryScope.USER, MemoryScope.PROJECT)):
            return ClassificationResult(
                action=ClassificationAction.PERSIST_DURABLE,
                memory_type=MemoryType.LONG_TERM,
                importance=0.7,
                reason="Explicitly tagged as long-term memory",
            )
        if hint_type in (MemoryType.WORKING, MemoryType.EXECUTION_OBSERVATION) and (
            scope is None or scope in (MemoryScope.AGENT_RUN, MemoryScope.CONVERSATION)
        ):
            return ClassificationResult(
                action=ClassificationAction.PERSIST_WORKING,
                memory_type=hint_type,
                importance=0.5,
                reason="Explicitly tagged as working/observation memory",
            )

        # 3. Deterministic pattern matching
        if scope is None or scope == MemoryScope.USER:
            for pat in self.USER_PREFERENCE_PATTERNS:
                if re.search(pat, clean_lower):
                    return ClassificationResult(
                        action=ClassificationAction.PERSIST_DURABLE,
                        memory_type=MemoryType.USER_PREFERENCE,
                        importance=0.85,
                        reason=f"Matched user preference pattern: {pat}",
                    )

        if scope is None or scope == MemoryScope.PROJECT:
            for pat in self.PROJECT_PATTERNS:
                if re.search(pat, clean_lower):
                    return ClassificationResult(
                        action=ClassificationAction.PERSIST_DURABLE,
                        memory_type=MemoryType.PROJECT,
                        importance=0.75,
                        reason=f"Matched project convention pattern: {pat}",
                    )

        # 4. Source-based heuristics
        if source.startswith("tool:") and (scope is None or scope in (MemoryScope.AGENT_RUN, MemoryScope.CONVERSATION)):
            return ClassificationResult(
                action=ClassificationAction.PERSIST_WORKING,
                memory_type=MemoryType.EXECUTION_OBSERVATION,
                importance=0.4,
                reason="Tool observation retained in working memory",
            )

        # 5. Default non-trivial information based on scope
        if scope == MemoryScope.PROJECT:
            return ClassificationResult(
                action=ClassificationAction.PERSIST_DURABLE,
                memory_type=MemoryType.PROJECT,
                importance=0.5,
                reason="Project context retained as project fact",
            )
        if scope == MemoryScope.USER:
            return ClassificationResult(
                action=ClassificationAction.PERSIST_DURABLE,
                memory_type=MemoryType.USER_PREFERENCE,
                importance=0.5,
                reason="User context retained as preference",
            )

        return ClassificationResult(
            action=ClassificationAction.PERSIST_WORKING,
            memory_type=MemoryType.WORKING,
            importance=0.5,
            reason="Standard context retained in working memory",
        )
