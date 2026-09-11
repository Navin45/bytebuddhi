"""Memory ranking strategies for ordering candidate memories."""

import math
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from app.domain.models.memory import MemoryItem, MemoryScope


@runtime_checkable
class MemoryRankingStrategy(Protocol):
    """Protocol for memory candidate ranking."""

    def rank(
        self,
        items: list[MemoryItem],
        query: str | None = None,
        target_scope: MemoryScope | None = None,
    ) -> list[tuple[MemoryItem, float]]:
        """Score and rank memory candidates in descending order of relevance."""
        ...


class StandardMemoryRankingStrategy(MemoryRankingStrategy):
    """Deterministic ranking combining keyword overlap, importance, recency, and scope match."""

    def __init__(
        self,
        weight_relevance: float = 0.4,
        weight_importance: float = 0.3,
        weight_recency: float = 0.2,
        weight_scope: float = 0.1,
        recency_half_life_hours: float = 48.0,
    ):
        self.w_rel = weight_relevance
        self.w_imp = weight_importance
        self.w_rec = weight_recency
        self.w_scope = weight_scope
        self.half_life = recency_half_life_hours

    def rank(
        self,
        items: list[MemoryItem],
        query: str | None = None,
        target_scope: MemoryScope | None = None,
    ) -> list[tuple[MemoryItem, float]]:
        now = datetime.now(UTC)
        scored: list[tuple[MemoryItem, float]] = []

        query_words = set(query.lower().split()) if query else set()

        for item in items:
            # 1. Relevance score (keyword overlap)
            rel_score = 0.5  # default baseline if no query
            if query_words:
                content_words = set(item.content.lower().split())
                overlap = len(query_words & content_words)
                total = len(query_words | content_words)
                rel_score = (overlap / total) if total > 0 else 0.0

            # 2. Importance score (normalized 0.0 to 1.0)
            imp_score = max(0.0, min(1.0, item.importance))

            # 3. Recency decay score
            created_aware = item.created_at if item.created_at.tzinfo else item.created_at.replace(tzinfo=UTC)
            age_hours = max(0.0, (now - created_aware).total_seconds() / 3600.0)
            rec_score = math.exp(-0.693 * (age_hours / self.half_life))

            # 4. Scope match score
            scope_score = 1.0 if target_scope and item.scope == target_scope else 0.5

            total_score = (
                (self.w_rel * rel_score)
                + (self.w_imp * imp_score)
                + (self.w_rec * rec_score)
                + (self.w_scope * scope_score)
            )

            scored.append((item, round(total_score, 4)))

        # Sort descending by total score
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
