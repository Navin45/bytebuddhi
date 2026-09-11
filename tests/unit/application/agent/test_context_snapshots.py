"""Unit tests for ContextSnapshot reference tracking."""

from app.application.agent.context import ContextEngine
from app.domain.models.artifact import Artifact
from app.domain.models.context_snapshot import ContextSnapshot
from app.domain.models.memory import MemoryItem, MemoryScope, MemoryType


def test_create_context_snapshot_references():
    engine = ContextEngine()

    mem1 = MemoryItem.create(
        scope=MemoryScope.USER,
        scope_id="u1",
        memory_type=MemoryType.USER_PREFERENCE,
        content="Prefer uv and ruff",
    )
    art1 = Artifact.create(
        artifact_type="command_stdout",
        size_bytes=50000,
        storage_ref="/storage/log.txt",
        summary="Build log",
    )

    ctx = engine.build_model_context(
        system_prompt="System instructions here.",
        messages=[{"role": "user", "content": "Help me refactor."}],
        memories=[mem1],
        artifacts=[art1],
    )

    snapshot = ContextSnapshot.from_model_context(
        run_id="run_456",
        iteration=1,
        model_context=ctx,
    )

    assert snapshot.run_id == "run_456"
    assert snapshot.iteration == 1
    assert snapshot.memory_ids == [mem1.id]
    assert snapshot.artifact_ids == [art1.id]
    assert len(snapshot.system_prompt_hash) == 16
    assert snapshot.total_estimated_tokens > 0

    d = snapshot.to_dict()
    assert d["snapshot_id"] == snapshot.snapshot_id
    assert d["memory_ids"] == [mem1.id]
    assert d["artifact_ids"] == [art1.id]
