"""Memory deduplication utilities to prevent redundant memory insertion."""

import hashlib
import re

from app.domain.models.memory import MemoryItem


class MemoryDeduplicator:
    """Detects and resolves duplicate or near-duplicate memories."""

    @staticmethod
    def normalize_text(text: str) -> str:
        """Normalize text by lowercasing, stripping punctuation, and collapsing whitespace."""
        lower = text.lower()
        no_punct = re.sub(r"[^\w\s]", "", lower)
        return " ".join(no_punct.split())

    @classmethod
    def compute_hash(cls, content: str) -> str:
        """Compute sha256 hash of normalized content."""
        norm = cls.normalize_text(content)
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()

    @classmethod
    def calculate_similarity(cls, text1: str, text2: str) -> float:
        """Calculate word-level Jaccard similarity between two texts."""
        words1 = set(cls.normalize_text(text1).split())
        words2 = set(cls.normalize_text(text2).split())

        if not words1 and not words2:
            return 1.0
        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)
        return intersection / union if union > 0 else 0.0

    @classmethod
    def find_duplicate(
        cls,
        candidate: MemoryItem,
        existing_items: list[MemoryItem],
        threshold: float = 0.85,
    ) -> MemoryItem | None:
        """Find an existing memory that matches or closely resembles candidate memory.

        Matches only if scope, scope_id, and memory_type are identical.
        """
        cand_hash = cls.compute_hash(candidate.content)

        for item in existing_items:
            # Must match scope and type boundary
            if (
                item.scope != candidate.scope
                or item.scope_id != candidate.scope_id
                or item.memory_type != candidate.memory_type
            ):
                continue

            # Exact hash match
            if cls.compute_hash(item.content) == cand_hash:
                return item

            # High semantic/lexical overlap
            sim = cls.calculate_similarity(candidate.content, item.content)
            if sim >= threshold:
                return item

        return None
