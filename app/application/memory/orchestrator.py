"""Central MemoryOrchestrator coordinating working, durable, and artifact memory."""

from collections.abc import Callable
from typing import Any

from app.application.memory.classifier import (
    ClassificationAction,
    MemoryClassifier,
)
from app.application.memory.deduplicator import MemoryDeduplicator
from app.application.memory.ranking import (
    MemoryRankingStrategy,
    StandardMemoryRankingStrategy,
)
from app.application.ports.output.llm.llm_provider import LLMProvider
from app.application.ports.output.memory.memory_store import MemoryStore
from app.application.ports.output.observability.meter import Counter, Histogram, Meter
from app.application.ports.output.observability.tracer import Tracer
from app.application.ports.output.storage.artifact_store import ArtifactStore
from app.domain.models.memory import (
    ExecutionObservation,
    MemoryItem,
    MemoryScope,
    MemoryType,
)
from app.domain.models.observability import MetricNames, SpanAttributes, SpanNames
from app.infrastructure.config.logger import get_logger
from app.infrastructure.observability.noop import NoOpMeter, NoOpTracer

logger = get_logger(__name__)


class MemoryOrchestrator:
    """Coordinates memory persistence, ranking, and retrieval across SQLite, Postgres, and ArtifactStore."""

    def __init__(
        self,
        working_store: MemoryStore,
        durable_store: MemoryStore,
        artifact_store: ArtifactStore | None = None,
        ranking_strategy: MemoryRankingStrategy | None = None,
        classifier: MemoryClassifier | None = None,
        event_hook: Callable[[str, dict[str, Any]], None] | None = None,
        embedding_provider: LLMProvider | None = None,
        tracer: Tracer | None = None,
        meter: Meter | None = None,
    ):
        self.working_store = working_store
        self.durable_store = durable_store
        self.artifact_store = artifact_store
        self.ranking = ranking_strategy or StandardMemoryRankingStrategy()
        self.classifier = classifier or MemoryClassifier()
        self.event_hook = event_hook
        self.embedding_provider = embedding_provider
        self.tracer = tracer or NoOpTracer()
        self.meter = meter or NoOpMeter()
        self._reads_counter: Counter = self.meter.create_counter(
            MetricNames.MEMORY_READS_TOTAL,
            unit="1",
            description="Total memory read/retrieval operations",
        )
        self._writes_counter: Counter = self.meter.create_counter(
            MetricNames.MEMORY_WRITES_TOTAL,
            unit="1",
            description="Total memory write operations",
        )
        self._failures_counter: Counter = self.meter.create_counter(
            MetricNames.MEMORY_FAILURES_TOTAL,
            unit="1",
            description="Total memory operation failures",
        )
        self._duration_hist: Histogram = self.meter.create_histogram(
            MetricNames.MEMORY_OPERATION_DURATION,
            unit="s",
            description="Memory operation duration in seconds",
        )

    def _emit(self, event_name: str, payload: dict[str, Any]) -> None:
        if self.event_hook:
            try:
                self.event_hook(event_name, payload)
            except Exception as e:
                logger.warning("Error in memory event hook", event=event_name, error=str(e))

    async def record_observation(
        self,
        observation: ExecutionObservation,
        scope: MemoryScope = MemoryScope.AGENT_RUN,
    ) -> MemoryItem:
        """Persist an execution observation into working memory."""
        memory_item = observation.to_memory_item(scope=scope)
        saved = await self.working_store.save(memory_item)
        self._emit(
            "MEMORY_CREATED",
            {
                "memory_id": saved.id,
                "scope": saved.scope.value,
                "type": saved.memory_type.value,
            },
        )
        return saved

    async def save_memory(
        self,
        content: str,
        scope: MemoryScope,
        scope_id: str,
        source: str = "user",
        hint_type: MemoryType | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryItem | None:
        """Classify and save a memory item into the appropriate store."""
        import time

        start_time = time.monotonic()
        with self.tracer.start_as_current_span(
            SpanNames.MEMORY_WRITE,
            attributes={
                SpanAttributes.MEMORY_SCOPE: scope.value,
                SpanAttributes.MEMORY_OPERATION: "save",
            },
        ):
            try:
                result = await self._save_memory_internal(
                    content=content,
                    scope=scope,
                    scope_id=scope_id,
                    source=source,
                    hint_type=hint_type,
                    metadata=metadata,
                )
                if result:
                    self._writes_counter.add(1, {"memory_scope": scope.value})
                return result
            except Exception:
                self._failures_counter.add(1, {"memory_scope": scope.value})
                raise
            finally:
                duration = time.monotonic() - start_time
                self._duration_hist.record(duration, {"memory_scope": scope.value})

    async def _save_memory_internal(
        self,
        content: str,
        scope: MemoryScope,
        scope_id: str,
        source: str = "user",
        hint_type: MemoryType | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryItem | None:
        decision = self.classifier.classify(
            content=content,
            source=source,
            scope=scope,
            hint_type=hint_type,
        )

        if decision.action == ClassificationAction.DISCARD:
            logger.debug("Memory candidate discarded by classifier", reason=decision.reason)
            return None

        target_store = (
            self.durable_store if decision.action == ClassificationAction.PERSIST_DURABLE else self.working_store
        )

        # Deduplication check: inspect existing items in scope
        try:
            existing = await target_store.search(
                scope=scope,
                scope_id=scope_id,
                memory_types=[decision.memory_type],
                limit=50,
            )
            candidate = MemoryItem.create(
                scope=scope,
                scope_id=scope_id,
                memory_type=decision.memory_type,
                content=content,
                source=source,
                importance=decision.importance,
                metadata=metadata,
            )

            # Generate embedding if saving durable memory and provider is available
            if decision.action == ClassificationAction.PERSIST_DURABLE and self.embedding_provider:
                try:
                    candidate.embedding = await self.embedding_provider.generate_embedding(content)
                    if candidate.embedding and len(candidate.embedding) != 1536:
                        logger.warning(
                            "Generated embedding dimension does not match Vector(1536)",
                            actual=len(candidate.embedding),
                            expected=1536,
                        )
                        candidate.embedding = None
                except Exception as ee:
                    logger.warning(
                        "Failed to generate embedding for durable memory item, saving without vector",
                        error=str(ee),
                    )

            dup = MemoryDeduplicator.find_duplicate(candidate, existing)
            if dup is not None:
                # Update existing memory instead of inserting duplicate
                dup.importance = max(dup.importance, decision.importance)
                dup.touch()
                if metadata:
                    dup.metadata.update(metadata)
                await target_store.update(dup)
                self._emit(
                    "MEMORY_UPDATED",
                    {"memory_id": dup.id, "scope": dup.scope.value, "reason": "deduplicated"},
                )
                return dup

            saved = await target_store.save(candidate)
            self._emit(
                "MEMORY_CREATED",
                {
                    "memory_id": saved.id,
                    "scope": saved.scope.value,
                    "type": saved.memory_type.value,
                },
            )
            return saved
        except Exception as e:
            logger.error("Failed to save memory item", scope=scope.value, error=str(e))
            return None

    async def retrieve_memories(
        self,
        query: str | None = None,
        scopes: list[tuple[MemoryScope, str]] | None = None,
        memory_types: list[MemoryType] | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """Retrieve, rank, and bound candidate memories across working and durable stores."""
        import time

        start_time = time.monotonic()
        with self.tracer.start_as_current_span(
            SpanNames.MEMORY_SEARCH,
            attributes={
                SpanAttributes.MEMORY_OPERATION: "retrieve",
            },
        ) as span:
            try:
                selected = await self._retrieve_memories_internal(
                    query=query,
                    scopes=scopes,
                    memory_types=memory_types,
                    limit=limit,
                )
                span.set_attribute(SpanAttributes.MEMORY_RESULT_COUNT, len(selected))
                self._reads_counter.add(1)
                return selected
            except Exception:
                self._failures_counter.add(1)
                raise
            finally:
                duration = time.monotonic() - start_time
                self._duration_hist.record(duration)

    async def _retrieve_memories_internal(
        self,
        query: str | None = None,
        scopes: list[tuple[MemoryScope, str]] | None = None,
        memory_types: list[MemoryType] | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        self._emit(
            "MEMORY_RETRIEVAL_STARTED",
            {"query": query, "scopes_count": len(scopes) if scopes else 0},
        )

        candidates: list[MemoryItem] = []

        if not scopes:
            return []

        # Generate query vector for semantic retrieval if embedding provider is available
        query_vector: list[float] | None = None
        if query and query.strip() and self.embedding_provider:
            try:
                query_vector = await self.embedding_provider.generate_embedding(query.strip())
                if query_vector and len(query_vector) != 1536:
                    logger.warning(
                        "Query embedding dimension does not match Vector(1536), falling back to text search",
                        actual=len(query_vector),
                        expected=1536,
                    )
                    query_vector = None
            except Exception as ee:
                logger.warning(
                    "Embedding generation failed for semantic retrieval, falling back to text search",
                    query=query,
                    error=str(ee),
                )
                query_vector = None

        # Query all allowed scopes across stores with Best-Effort error isolation
        for scope_type, s_id in scopes:
            # 1. Query working store (for AGENT_RUN, retrieve recent context without query restriction)
            try:
                working_query = None if scope_type == MemoryScope.AGENT_RUN else query
                working_items = await self.working_store.search(
                    query=working_query,
                    scope=scope_type,
                    scope_id=s_id,
                    memory_types=memory_types,
                    limit=limit * 2,
                )
                candidates.extend(working_items)
            except Exception as we:
                logger.warning(
                    "Working store query failed, continuing best-effort",
                    scope=scope_type.value,
                    error=str(we),
                )

            # 2. Query durable store
            try:
                durable_items = await self.durable_store.search(
                    query=query,
                    scope=scope_type,
                    scope_id=s_id,
                    memory_types=memory_types,
                    limit=limit * 2,
                    query_vector=query_vector,
                )
                candidates.extend(durable_items)
            except Exception as de:
                logger.warning(
                    "Durable store query failed, continuing best-effort",
                    scope=scope_type.value,
                    error=str(de),
                )

        # Deduplicate candidates across queries by ID
        unique_map: dict[str, MemoryItem] = {item.id: item for item in candidates}
        unique_items = list(unique_map.values())

        # Rank candidates using strategy
        primary_scope = scopes[0][0] if scopes else None
        ranked = self.ranking.rank(unique_items, query=query, target_scope=primary_scope)

        # Bounded selection
        selected = [item for item, _ in ranked[:limit]]

        self._emit(
            "MEMORY_RETRIEVAL_COMPLETED",
            {"total_candidates": len(unique_items), "selected_count": len(selected)},
        )
        return selected

    async def delete_memory(
        self,
        memory_id: str,
        scope: MemoryScope,
        scope_id: str,
    ) -> bool:
        """Delete a memory item from either working or durable store."""
        deleted_working = await self.working_store.delete(memory_id, scope, scope_id)
        deleted_durable = await self.durable_store.delete(memory_id, scope, scope_id)
        success = deleted_working or deleted_durable
        if success:
            self._emit("MEMORY_DELETED", {"memory_id": memory_id, "scope": scope.value})
        return success
