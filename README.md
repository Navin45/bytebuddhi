# ByteBuddhi — Production-Grade AI Coding & Agent Platform

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128+-009688.svg)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.0+-orange.svg)](https://github.com/langchain-ai/langgraph)
[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-1.30+-purple.svg)](https://opentelemetry.io/)
[![Package Manager: uv](https://img.shields.io/badge/uv-astral-green.svg)](https://astral.sh/uv)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Tests](https://img.shields.io/badge/tests-264%20passed-brightgreen.svg)]()

ByteBuddhi is a production-grade AI coding and multi-agent execution platform built on clean hexagonal architecture. It provides reliable agent runtimes, durable state with PostgreSQL checkpoints, working memory with SQLite WAL, structure-aware code intelligence powered by Tree-sitter, unified capability integrations via native tools, connectors, and the Model Context Protocol (MCP), multi-agent delegation orchestration, and first-class OpenTelemetry observability.

---

## Architectural Highlights

```text
                                 Client Layer
                 (REST API / SSE Streaming / Future CLI & IDE)
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │   MultiAgentOrchestrator   │
                        │ (DAG scheduling, bounds)  │
                        └─────────────┬─────────────┘
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │       AgentRuntime        │
                        │  (LangGraph state-node)   │
                        └──────┬──────┬──────┬──────┘
                               │      │      │
           ┌───────────────────┘      │      └───────────────────┐
           ▼                          ▼                          ▼
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│    ContextEngine    │    │    ToolExecutor     │    │   Observability     │
│ - Token budgeting   │    │ - Policy validation │    │ - Trace & Span ports│
│ - Priority ranking  │    │ - Command execution │    │ - Meter & Histograms│
│ - Context snapshots │    │ - Output bounding   │    │ - Privacy redaction │
└──────────┬──────────┘    └──────────┬──────────┘    └──────────┬──────────┘
           │                          │                          │
           ▼                          ▼                          ▼
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│  MemoryOrchestrator │    │ Capability Registry │    │ OpenTelemetry SDK   │
│ - SQLite WAL (run)  │    │ - Native Tools      │    │ - OTLP / Console    │
│ - Postgres pgvector │    │ - GitHub Connector  │    │ - Low-cardinality   │
│ - ArtifactStore     │    │ - MCP Client Mgr    │    │ - Failure isolated  │
└─────────────────────┘    └─────────────────────┘    └─────────────────────┘
```

- **One Unified Capability Model**: Agents invoke tools via uniform capability contracts (`ToolDefinition`, `ToolCall`, `ToolResult`), whether backed by native code, local shell, external connectors (GitHub), or Model Context Protocol (MCP) servers.
- **Hierarchical Memory & Context**: Clear separation between active conversation history, ephemeral run-scoped working memory (SQLite WAL), durable cross-session memory with semantic embeddings (PostgreSQL + pgvector), and artifact storage.
- **Strict Security & Authorization Policy**: Untrusted model-generated parameters pass through path-traversal prevention, workspace confinement, shell command policy checks, and self-approval denial.
- **Production-Grade Observability**: Decoupled application-owned telemetry ports (`Tracer`, `Meter`, `CorrelationContext`) backed by OpenTelemetry. Privacy by construction ensures zero prompt texts, thought chains, secrets, or raw tool payloads leak into spans.

---

## Tech Stack

| Component | Technology | Description |
|---|---|---|
| **Language & Runtime** | Python 3.13+ | AsyncIO-driven execution engine |
| **API Framework** | FastAPI | High-performance async REST API with SSE streaming |
| **Agent State Machine** | LangGraph & LangChain | State-node agent loop with durable checkpointing |
| **Code Intelligence** | Tree-sitter | AST parsing and symbol extraction for Python, JS, and TS |
| **Database & Vector** | PostgreSQL + pgvector | Relational entities, checkpointing, and semantic embeddings |
| **Ephemeral Cache** | Redis 7+ | Fast operational caching and rate limiting |
| **Working Memory** | SQLite (WAL mode) | Isolated, thread-safe, run-scoped operational store |
| **External Protocols** | MCP (Model Context Protocol) | Standardized client integration for external capabilities |
| **Observability** | OpenTelemetry | Distributed tracing, metrics histograms, and semantic spans |
| **Package Manager** | uv (Astral) | Lightning-fast Python package and virtualenv manager |
| **Quality Gate** | Ruff, Mypy, Pytest | Formatting, linting, strict static typing, and 264+ tests |

---

## Project Structure

```text
bytebuddhi/
├── app/
│   ├── application/              # Use cases, orchestrators, ports, policies
│   │   ├── agent/                # AgentRuntime, Orchestrator, ContextEngine
│   │   ├── code/                 # Code intelligence indexing & AST services
│   │   ├── memory/               # Memory classification, ranking, orchestrator
│   │   ├── policy/               # Command policy & tool authorization engine
│   │   ├── ports/                # Abstract input & output ports
│   │   └── tools/                # Tool definitions, registry, executor
│   ├── domain/                   # Enterprise business entities & value objects
│   │   ├── models/               # Domain models (agent, memory, code, telemetry)
│   │   └── value_objects/        # Languages, emails, credentials, paths
│   ├── infrastructure/           # External technology adapters & implementations
│   │   ├── config/               # Settings, logger, security configuration
│   │   ├── connectors/           # GitHub & external REST service adapters
│   │   ├── execution/            # LocalProcessManager & sandboxed OS execution
│   │   ├── http/                 # Bounded external HTTP client with retries
│   │   ├── llm/                  # OpenAI & Anthropic model gateways
│   │   ├── mcp/                  # Model Context Protocol client manager
│   │   ├── observability/        # OpenTelemetry tracer, meter, and providers
│   │   ├── parser/               # Tree-sitter extractors for Python/JS/TS
│   │   ├── persistence/          # PostgreSQL repositories, pgvector, SQLite
│   │   └── storage/              # LocalArtifactStore with directory confinement
│   └── interfaces/               # Primary adapters & presentation
│       └── api/                  # FastAPI routes, schemas, middleware, SSE
├── tests/                        # Comprehensive test suite (264+ tests)
│   ├── unit/                     # Domain, application, and infrastructure unit tests
│   ├── integration/              # End-to-end multi-agent, memory, OTel flows
│   ├── security/                 # Adversarial penetration & sandbox escape tests
│   └── fixtures/                 # Reusable test fixtures and mocks
├── alembic/                      # Database migration revisions
├── scripts/                      # Operational automation & database migration scripts
├── docs/                         # Engineering specifications (HLD, LLD, System Design, Mermaid)
├── .env.example                  # Environment variable configuration template
├── .gitignore                    # Comprehensive ignore rules
├── .python-version               # Python 3.13 baseline pinning
├── alembic.ini                   # Alembic database migration configuration
├── Dockerfile                    # Containerization image definition
├── docker-compose.yml            # Local development orchestration (Redis, API)
├── main.py                       # Application bootstrap entry point
├── pyproject.toml                # Project metadata, dependencies & tool configs
├── requirements.txt              # Exported requirements reference
└── uv.lock                       # Deterministic dependency lockfile
```

---

## Quick Start

### Prerequisites

- **Python 3.13+** installed on your system
- **Docker & Docker Compose** (for running Redis)
- **uv** (astral.sh package manager)
- **PostgreSQL 16+ with pgvector** (e.g. Supabase or local PostgreSQL)

### 1. Clone & Setup Environment

```bash
# Clone the repository
git clone https://github.com/Navin45/bytebuddhi.git
cd bytebuddhi

# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Synchronize dependencies and create virtual environment
uv sync
```

### 2. Configure Environment Variables

```bash
cp .env.example .env
# Edit .env with your PostgreSQL database URL, Redis URL, and API keys (OpenAI / Anthropic)
```

Key environment configuration variables:
```env
# Application & Database
DATABASE_URL=postgresql+asyncpg://bytebuddhi:password@localhost:5432/bytebuddhi
REDIS_URL=redis://localhost:6379/0
JWT_SECRET_KEY=your-secure-jwt-secret-key-min-32-chars

# LLM Providers
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Observability (OpenTelemetry)
TELEMETRY_ENABLED=true
OTEL_SERVICE_NAME=bytebuddhi
OTEL_EXPORTER=console          # "console" | "otlp" | "none"
OTEL_OTLP_ENDPOINT=http://localhost:4317
OTEL_TRACING_ENABLED=true
OTEL_METRICS_ENABLED=true
```

### 3. Start Supporting Infrastructure

```bash
# Start Redis cache container
docker-compose up -d redis
```

### 4. Run Database Migrations

```bash
uv run alembic upgrade head
```

### 5. Launch the Server

```bash
# Development mode with auto-reload
uv run uvicorn app.interfaces.api.main:app --host 0.0.0.0 --port 8000 --reload
```

- API Base: `http://localhost:8000`
- Interactive OpenAPI Docs: `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/api/v1/health`

---

## Verification & Quality Gate

ByteBuddhi maintains a 100% passing automated test suite with zero tolerance for regressions.

```bash
# Run the complete test suite (264+ unit, integration, and security tests)
uv run pytest

# Check linting rules (Ruff)
uv run ruff check .

# Check formatting (Ruff)
uv run ruff format --check .

# Static type checking (Mypy)
uv run mypy app/domain/models/observability.py app/application/ports/output/observability/ app/infrastructure/observability/
```

---

## Core API Reference

All endpoints are versioned under `/api/v1`.

### Health & Diagnostics
- `GET /api/v1/health`: Basic API health check and version metadata.
- `GET /api/v1/health/db`: Database connectivity verification.

### Authentication
- `POST /api/v1/auth/register`: Create user account with bcrypt password hashing.
- `POST /api/v1/auth/login`: Authenticate credentials, returns JWT access and refresh tokens.
- `POST /api/v1/auth/refresh`: Issue new access token using valid refresh token.
- `GET /api/v1/auth/me`: Retrieve profile of currently authenticated user.

### Projects & Files
- `POST /api/v1/projects`: Create project tracking a workspace codebase.
- `GET /api/v1/projects`: List projects owned by authenticated user.
- `GET /api/v1/projects/{id}`: Fetch detailed project metadata.
- `PUT /api/v1/projects/{id}`: Update project details.
- `DELETE /api/v1/projects/{id}`: Delete project and associated records.
- `POST /api/v1/files/upload`: Upload file for code parsing and indexing.
- `GET /api/v1/files/{id}`: Fetch file record and indexing status.

### Agent Chat & SSE Streaming
- `POST /api/v1/chat/conversations`: Initialize a new conversation thread.
- `GET /api/v1/chat/conversations`: List active conversations.
- `GET /api/v1/chat/conversations/{id}`: Fetch conversation history and messages.
- `POST /api/v1/chat/conversations/{id}/messages`: Submit message and stream agent execution via Server-Sent Events (`text/event-stream`), emitting real-time tool execution events, reasoning updates, and final responses.
- `POST /api/v1/agent/feedback`: Submit user feedback for agent evaluation runs.

---

## Engineering Documentation

Detailed production-grade architectural and design specifications are maintained in [`docs/`](docs/):

- **[High-Level Design (HLD)](docs/hld.md)**: System vision, C4 container models, subsystem breakdown, technology stack rationale, and non-functional requirements.
- **[Low-Level Design (LLD)](docs/lld.md)**: Class contracts, hexagonal layer ports, state machine transitions, priority token budgeting algorithm, and concurrency models.
- **[System Design](docs/system_design.md)**: Deployment topology, multi-tier data architecture (PostgreSQL with pgvector, Redis, SQLite WAL, ArtifactStore), sandboxed OS process execution, and resilience strategies.
- **Architecture Flowcharts (Mermaid)**:
  - [`docs/system_architecture.mermaid`](docs/system_architecture.mermaid): C4 container & component topology.
  - [`docs/agent_runtime_flow.mermaid`](docs/agent_runtime_flow.mermaid): Single-agent reasoning and tool execution loop sequence.
  - [`docs/multi_agent_orchestration.mermaid`](docs/multi_agent_orchestration.mermaid): DAG task scheduling, concurrency semaphore bounds, and cascading cancellation.
  - [`docs/data_and_memory_architecture.mermaid`](docs/data_and_memory_architecture.mermaid): Tiered storage and memory hierarchy.

---

## Security & Privacy Guarantee

- **Workspace Confinement**: All filesystem operations are validated against safe workspace boundaries to prevent directory traversal (`../`) attacks.
- **Command Authorization**: Modifying, network-accessing, and destructive OS commands are gated by policy engines requiring explicit caller permissions.
- **Privacy by Construction**: Automated redaction sanitizes API keys, bearer tokens, passwords, and private identifiers before any telemetry span or metric is emitted.
- **Strict Data Bounding**: Outputs exceeding 6,000 characters are archived to `ArtifactStore` rather than bloating LLM contexts or metric backends.

---

## License

ByteBuddhi is open-source software licensed under the [MIT License](LICENSE).
