# System Design — ByteBuddhi Platform

> **Document Version:** 1.0.0  
> **Status:** Production-Grade Baseline  
> **Focus:** Deployment Topology, Data Storage Architecture, Distributed Caching, Security Boundaries, Resilience, and Observability

---

## 1. System Topology & Deployment Architecture

ByteBuddhi is architected as a modular, cloud-ready service that can be deployed as a containerized cluster or run locally for low-latency developer environments.

```text
                             Internet / Clients
                                     │
                                     ▼
                       ┌───────────────────────────┐
                       │   Ingress / Load Balancer │
                       │    (TLS Termination, SSL) │
                       └─────────────┬─────────────┘
                                     │
                                     ▼
                       ┌───────────────────────────┐
                       │    FastAPI Application    │
                       │    (Uvicorn Workers)      │
                       └──────┬──────┬──────┬──────┘
                              │      │      │
           ┌──────────────────┘      │      └──────────────────┐
           ▼                         ▼                         ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│  Redis Cluster 7+   │   │  PostgreSQL 16+     │   │ OpenTelemetry       │
│ - Rate limiting     │   │  (pgvector)         │   │ Collector           │
│ - Session cache     │   │ - User / Projects   │   │ - OTLP gRPC/HTTP    │
│ - Connection state  │   │ - Durable Memory    │   │ - Prometheus/Jaeger │
└─────────────────────┘   │ - Checkpoint State  │   └─────────────────────┘
                          └─────────────────────┘
```

---

## 2. Multi-Tiered Data Architecture

ByteBuddhi separates data storage according to **durability, concurrency, and locality**:

```text
┌───────────────────────────┬───────────────────────────┬───────────────────────────┐
│ Tier                      │ Storage Engine            │ Purpose & Scope           │
├───────────────────────────┼───────────────────────────┼───────────────────────────┤
│ **Shared Durable Tier**   │ PostgreSQL 16+ (pgvector) │ Shared system of record,  │
│                           │                           │ users, conversations,     │
│                           │                           │ semantic embeddings.      │
├───────────────────────────┼───────────────────────────┼───────────────────────────┤
│ **Ephemeral Cache Tier**  │ Redis 7+                  │ Transient cache. HTTP     │
│                           │                           │ rate limits are           │
│                           │                           │ process-local per worker. │
├───────────────────────────┼───────────────────────────┼───────────────────────────┤
│ **Run-Scoped Working Tier**│ SQLite (WAL Mode)        │ Low-latency run memory,   │
│                           │                           │ observation log, TTL.     │
├───────────────────────────┼───────────────────────────┼───────────────────────────┤
│ **Large Payload Tier**    │ Local Artifact Store      │ Payloads > 6,000 chars,   │
│                           │ (Filesystem)              │ files, process outputs.   │
└───────────────────────────┴───────────────────────────┴───────────────────────────┘
```

### 2.1 PostgreSQL with pgvector (Authoritative Shared State)
- **Tables**: `users`, `projects`, `files`, `conversations`, `messages`, `memory_items`, `checkpoints`.
- **Vector Search**: Uses `vector(1536)` columns with HNSW / IVFFlat indexing for cosine similarity retrieval across user, project, and global memory scopes.
- **Connection Pooling**: SQLAlchemy async engine backed by `asyncpg` with pool sizing (`pool_size=20`, `max_overflow=10`).

### 2.2 Redis (Caching)
- Redis is available for cache and optional operational use.
- HTTP API rate limiting is **process-local in-memory per worker**. It is not a distributed Redis limiter. `X-Forwarded-For` is honored only when the direct peer is in `TRUSTED_PROXY_IPS`.

### 2.3 SQLite in WAL Mode (Run-Scoped Operational Memory)
- **Local Isolation**: Each agent run uses an embedded SQLite database file configured with `PRAGMA journal_mode=WAL;` and `PRAGMA synchronous=NORMAL;`.
- **Concurrency Guarantees**: Multiple concurrent readers can query state while write transactions remain ultra-short (< 5ms), preventing table lock contention.
- **Auto Cleanup**: Ephemeral memory items carry TTL timestamps and are purged automatically upon task completion.

---

## 3. Sandboxing & Process Security Architecture

```text
                 Model Tool Call: "run_command"
                              │
                              ▼
                 ┌───────────────────────────┐
                 │     ToolPolicyEngine      │
                 │ - Check permissions       │
                 │ - Deny self-approval      │
                 └─────────────┬─────────────┘
                               │ Approved
                               ▼
                 ┌───────────────────────────┐
                 │    LocalProcessManager    │
                 │ - Workspace path jail     │
                 │ - Sanitized environment   │
                 │ - Timeout watchdogs       │
                 └─────────────┬─────────────┘
                               │
                               ▼
                 ┌───────────────────────────┐
                 │      OS Subprocess        │
                 │ (Non-root, bounded stdout)│
                 └───────────────────────────┘
```

1. **Workspace Confinement**: Operations are sandboxed inside the user's project workspace directory. Paths resolving outside via symlinks or `..` are blocked before execution.
2. **Command Risk Gating**: Commands are parsed and categorized:
   - *Read-Only*: `git status`, `ls`, `grep` (Executed automatically).
   - *Modifying*: `git checkout -b`, file writes (Checked against permissions).
   - *Destructive / Privileged*: `rm -rf`, package installations (Require human approval).
3. **Stream Safety & Timeouts**: Process stdout/stderr streams are read asynchronously. If execution exceeds the task timeout (e.g. 120s), the process tree is terminated with SIGTERM followed by SIGKILL.

---

## 4. Observability & Telemetry Pipeline

ByteBuddhi implements an enterprise telemetry architecture conforming to the OpenTelemetry standard:

```text
┌────────────────────────────────────────────────────────┐
│ ByteBuddhi Runtime Instrumentation                     │
│  (agent.run, agent.orchestration, tool.execute, etc.)  │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ Redaction & Privacy Filter (RedactionPolicy)           │
│  - Masks API keys, bearer tokens, passwords            │
│  - Caps strings at 500 chars, arrays at 50 elements    │
│  - Restricts metric dimensions to low-cardinality keys │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ OpenTelemetry SDK (TracerProvider & MeterProvider)     │
│  - BatchSpanProcessor (non-blocking)                   │
│  - Defensive fallback to NoOp on failure               │
└──────────┬───────────────────────────────┬─────────────┘
           │ gRPC / Protobuf               │ Console
           ▼                               ▼
┌─────────────────────┐         ┌─────────────────────┐
│ OpenTelemetry       │         │ Developer Console   │
│ Collector (OTLP)    │         │ (Local Debugging)   │
└──────────┬──────────┘         └─────────────────────┘
           │
     ┌─────┴──────────────┐
     ▼                    ▼
┌──────────────┐    ┌──────────────┐
│ Prometheus   │    │ Jaeger /     │
│ (Metrics)    │    │ Grafana Tempo│
│              │    │ (Traces)     │
└──────────────┘    └──────────────┘
```

---

## 5. Resilience & Fault Tolerance Strategies

| Failure Scenario | Mitigation Strategy | Result |
|---|---|---|
| **LLM Rate Limits (HTTP 429)** | Exponential backoff with jitter inspecting `Retry-After` header. | Requests retry safely without overwhelming upstream APIs. |
| **LLM Provider Outage** | Pluggable `ModelGateway` with fallback support from OpenAI to Anthropic. | Continuous service availability during provider degradation. |
| **Subprocess Hang / Deadlock** | `asyncio.wait_for` timeout watchdog on process streams. | Process terminated; structured `TimeoutError` returned. |
| **Child Agent Critical Failure** | Cascading cooperative cancellation via `asyncio.Event`. | Sibling sub-agents cancel cleanly, preserving token budgets. |
| **Telemetry Network Drop** | Application ports catch all telemetry exceptions defensively. | Business agent execution completes with zero interruption. |
| **Massive Tool Output (> 6KB)**| Automatic truncation and archival to `LocalArtifactStore`. | Context window preserved; model receives compact reference. |

---

## 6. Capacity Planning & Cost Controls

1. **Iteration Budgets**: Single-agent loops are capped at a maximum number of iterations (`max_iterations=15`) to prevent runaway loops.
2. **Global Multi-Agent Token Pooling**: Multi-agent runs enforce an atomic global token cap (`max_global_tokens=64,000`). Tasks requesting budget beyond the limit fail fast before model calls occur.
3. **Concurrency Throttling**: Child agents are bounded by `asyncio.Semaphore(max_concurrent_children=4)` to avoid CPU and network saturation.
4. **Context Window Optimization**: `ContextEngine` ranks and deduplicates memories, pruning conversation turns to stay strictly within provider context limits.
