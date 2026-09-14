# ByteBuddhi

ByteBuddhi is an AI coding and agent platform. REST, CLI, and VS Code all execute the same path:

```text
Client
  → ExecuteTaskUseCase
  → trusted ExecutionContext
  → AgentRuntime / MultiAgentOrchestrator
  → ModelGateway → provider adapter
  → ToolExecutor / ToolPolicyEngine
```

The runtime does not change when you pick a different model. Provider credentials enable adapters; they do not redefine the architecture.

## Architecture

```text
REST API / CLI / VS Code
        ↓
ExecuteTaskUseCase
        ↓
ExecutionContext
        ↓
AgentRuntime / MultiAgentOrchestrator
        ↓
ModelGateway (catalog + routing)
        ↓
Provider adapters (OpenAI, Anthropic, OpenAI-compatible, …)
        ↓
ToolExecutor → Memory, Artifacts, Process, Web, MCP, Connectors
```

## Capabilities

- Single-agent loop and bounded multi-agent delegation
- Workspace-scoped filesystem and command tools
- Memory (working SQLite + durable PostgreSQL) and artifacts
- Code intelligence (Tree-sitter)
- Connectors and MCP behind the same tool policy
- Web research with SSRF controls
- OpenTelemetry traces/metrics with redaction
- JWT API (password, Google, GitHub), local CLI principal, thin VS Code client

## Installation

```bash
git clone https://github.com/Navin45/bytebuddhi.git
cd bytebuddhi
uv sync
cp .env.example .env
```

Requires Python 3.13+, PostgreSQL 16+ with pgvector, and Redis when distributed cancellation is enabled.

## Configuration

`.env` is for local development only. Production injects the same variables from a secret manager. See `.env.example`.

Authoritative settings live in `app/infrastructure/config/settings.py` (`Settings`). API, CLI, and Docker read that model.

## Model selection

```env
DEFAULT_MODEL_PROVIDER=openai
DEFAULT_MODEL_NAME=gpt-4-turbo-preview
OPENAI_API_KEY=...
```

`DEFAULT_MODEL_*` is only the default. Users may select any **enabled and available** catalog model without restarting:

- `GET /api/v1/models`
- `POST /api/v1/chat/conversations/{id}/messages` with `{ "model": { "provider", "model" } }`
- `bytebuddhi run --provider openai --model …`
- VS Code: **ByteBuddhi: Select Model**

Credentials stay server-side. There is no user BYOK. Custom OpenAI-compatible URLs are operator-configured only. See [Model gateway](docs/models.md).

You do not need every provider key. Enable only the providers you run.

## Running locally

```bash
docker compose up -d redis
uv run alembic upgrade head
uv run uvicorn app.interfaces.api.main:app --host 127.0.0.1 --port 8000 --reload
```

- API: `http://127.0.0.1:8000/api/v1`
- OpenAPI (debug): `http://127.0.0.1:8000/api/docs`
- Liveness: `GET /api/v1/health/live`
- Readiness: `GET /api/v1/health/ready`

## Docker / production

```bash
docker build -t bytebuddhi:local .
POSTGRES_PASSWORD=... JWT_SECRET_KEY=... OPENAI_API_KEY=... \
  docker compose -f docker-compose.prod.yml up --build
```

`docker-compose.yml` is development (`--reload`). `docker-compose.prod.yml` is the production-shaped API + PostgreSQL + Redis stack. Browser rendering stays off unless isolated. Full operator contract: [Production](docs/production.md).

## CLI

```bash
uv run bytebuddhi --help
uv run bytebuddhi --version
uv run bytebuddhi models
uv run bytebuddhi run --user-id <uuid> --project <uuid> --provider openai --model gpt-4-turbo-preview "Explain this repository"
```

The CLI is an in-process adapter over `ExecuteTaskUseCase`, not a second runtime. See [CLI](docs/cli.md).

## VS Code

```bash
cd vscode-extension
npm install
npm run compile
npm test
npm run package
```

Sign in with JWT. Select models from the backend catalog. See [VS Code](docs/vscode.md).

## Security

- Trusted identity is never taken from prompts, tool args, or web content
- Workspace containment, command policy, and HIGH-risk approval provenance
- SSRF controls for web fetch/render
- No secrets in catalog responses, events, or default logs
- Production fail-closed JWT, CORS, workspace mode, and Playwright isolation

## Development and testing

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app/
uv run pytest tests/ -v
cd vscode-extension && npm run compile && npm run lint && npm test
```

Live LLM smoke tests are opt-in (`LIVE_LLM_PROVIDER` + provider key) and are not required for the default suite. CI stores live credentials as GitHub environment secrets and does not run that job on fork pull requests.

## Limitations

Documented in [Production](docs/production.md). Notably: process-local rate limits/admission, local/PV artifacts (not object storage), no durable event replay, Playwright off unless isolated, no silent model failover.

## Documentation

- [Production](docs/production.md)
- [Model gateway](docs/models.md)
- [HLD](docs/hld.md) / [LLD](docs/lld.md)
- [CLI](docs/cli.md) / [VS Code](docs/vscode.md)
- [Web research](docs/web_research.md)

## License

MIT. See [LICENSE](LICENSE).
