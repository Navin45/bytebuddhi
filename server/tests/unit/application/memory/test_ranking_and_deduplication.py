"""Unit tests for MemoryClassifier, MemoryRankingStrategy, and MemoryDeduplicator."""

from app.application.memory.classifier import (
    ClassificationAction,
    MemoryClassifier,
)
from app.application.memory.deduplicator import MemoryDeduplicator
from app.application.memory.ranking import StandardMemoryRankingStrategy
from app.domain.models.memory import MemoryItem, MemoryScope, MemoryType


def test_memory_classifier_preferences():
    classifier = MemoryClassifier()

    res = classifier.classify("I prefer using pytest over unittest", source="user")
    assert res.action == ClassificationAction.PERSIST_DURABLE
    assert res.memory_type == MemoryType.USER_PREFERENCE
    assert res.importance >= 0.8


def test_memory_classifier_project_rules():
    classifier = MemoryClassifier()

    res = classifier.classify("Our project convention is to use hexagonal architecture", source="user")
    assert res.action == ClassificationAction.PERSIST_DURABLE
    assert res.memory_type == MemoryType.PROJECT
    assert res.importance >= 0.7


def test_memory_classifier_discard_noise():
    classifier = MemoryClassifier()

    res1 = classifier.classify("ok", source="user")
    assert res1.action == ClassificationAction.DISCARD

    res2 = classifier.classify("   ", source="user")
    assert res2.action == ClassificationAction.DISCARD


def test_memory_ranking_strategy():
    strategy = StandardMemoryRankingStrategy()

    item_high = MemoryItem.create(
        scope=MemoryScope.PROJECT,
        scope_id="proj_1",
        memory_type=MemoryType.PROJECT,
        content="FastAPI backend setup with PostgreSQL and Alembic migrations",
        importance=0.9,
    )
    item_low = MemoryItem.create(
        scope=MemoryScope.PROJECT,
        scope_id="proj_1",
        memory_type=MemoryType.LONG_TERM,
        content="random unrelated scratchpad note",
        importance=0.2,
    )

    ranked = strategy.rank(
        [item_low, item_high],
        query="PostgreSQL migrations",
        target_scope=MemoryScope.PROJECT,
    )

    assert len(ranked) == 2
    assert ranked[0][0].id == item_high.id
    assert ranked[0][1] > ranked[1][1]


def test_memory_deduplicator():
    item1 = MemoryItem.create(
        scope=MemoryScope.USER,
        scope_id="user_1",
        memory_type=MemoryType.USER_PREFERENCE,
        content="Always write clean code with type annotations!",
    )
    item2 = MemoryItem.create(
        scope=MemoryScope.USER,
        scope_id="user_1",
        memory_type=MemoryType.USER_PREFERENCE,
        content="always write clean code with type annotations",
    )
    item_different_scope = MemoryItem.create(
        scope=MemoryScope.USER,
        scope_id="user_2",
        memory_type=MemoryType.USER_PREFERENCE,
        content="always write clean code with type annotations",
    )

    # Identical content in same scope -> duplicate
    dup = MemoryDeduplicator.find_duplicate(item2, [item1])
    assert dup is not None
    assert dup.id == item1.id

    # Identical content in different scope -> NOT duplicate
    no_dup = MemoryDeduplicator.find_duplicate(item_different_scope, [item1])
    assert no_dup is None
