# ByteBuddhi

ByteBuddhi is an AI coding and agent platform. The CLI and terminal interface talk to one gateway. The gateway is the existing FastAPI application. Application use cases stay authoritative.

```text
Textual TUI / CLI
        ↓
GatewayClient
        ↓
FastAPI
        ↓
Run protocol
        ↓
AgentRuntime
```

PostgreSQL is the durable source of truth for runs and events. Redis fans live notifications out to gateway workers. A WebSocket delivers those events to the client. Disconnecting the socket does not cancel the run. `POST /api/v1/runs/{run_id}/cancel` does.

Phase 1 established the gateway transport. Phase 2 makes `POST /api/v1/runs` return `202` with `queued` and streams the run. It does not add a second agent runtime.

```text
CLI / TUI / VS Code
        ↓
ByteBuddhi Gateway
        ↓
FastAPI
        ↓
Application use cases
        ↓
AgentRuntime
        ↓
Models / Tools / Memory / MCP / DB
```

`bytebuddhi run --embedded` still calls `ExecuteTaskUseCase` in-process. That mode is explicit. A gateway failure does not fall back to it.

The runtime does not change when you pick a different model. Provider credentials enable adapters; they do not redefine the architecture.

## Architecture

```text
CLI / VS Code
        ↓
GatewayClient or HTTP
        ↓
FastAPI
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
- JWT API (password, Google, GitHub). The gateway is the authority for CLI identity. `--embedded` can still use a local principal.

## Installation

### One-Command CLI Install

**macOS / Linux (bash/zsh):**
```bash
curl -fsSL https://github.com/Navin45/bytebuddhi/releases/latest/download/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://github.com/Navin45/bytebuddhi/releases/latest/download/install.ps1 | iex
```

### Desktop App

Download installers from [GitHub Releases](https://github.com/Navin45/bytebuddhi/releases/latest):
- **Windows:** `ByteBuddhi-Setup-<version>.exe`
- **macOS:** `ByteBuddhi-<version>-arm64.dmg` / `ByteBuddhi-<version>-x64.dmg`
- **Linux:** `ByteBuddhi-<version>-x64.AppImage` / `.deb`

### Run

```bash
bytebuddhi
```

Launch the terminal UI:
```bash
bytebuddhi tui
```

Check for updates:
```bash
bytebuddhi update --check
```

### Developer Setup (From Source)

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
uv run bytebuddhi gateway start
uv run bytebuddhi login --provider google
uv run bytebuddhi models
uv run bytebuddhi run "Explain this repository"
```

Normal CLI commands call the gateway with `Authorization: Bearer`. `bytebuddhi run` creates a run (`202`) and prints events as they arrive. `--json` prints one JSON object per line. The local gateway listens on `127.0.0.1:8765` unless you set `BYTEBUDDHI_GATEWAY_HOST` / `BYTEBUDDHI_GATEWAY_PORT` or pass `--host` / `--port`. `bytebuddhi serve` runs that same FastAPI app in the foreground. Production Gunicorn is unchanged.

`bytebuddhi run --embedded` is the in-process path. See [CLI](docs/cli.md).

## Terminal interface

```bash
uv run bytebuddhi tui
```

`bytebuddhi tui` is another gateway client. It uses the same URL resolution, local gateway startup, credentials, and `GatewayClient` as the CLI. It does not execute agents, and it does not read PostgreSQL or Redis.

A local URL starts the managed gateway when it is not already running. `BYTEBUDDHI_GATEWAY_URL=https://...` connects to that remote gateway and does not start a local process. There is no embedded TUI mode. A missing credential tells you to run `bytebuddhi login`.

Enter sends one run. Shift+Enter inserts a newline. Esc requests cancellation and the transcript waits for `run_cancelled`. Closing the TUI disconnects the client and leaves the run running on the gateway. A dropped WebSocket reconnects to the same run id, replays from the last sequence, and does not create a second run. `run_interrupted` is shown as INTERRUPTED.

## Desktop

```bash
cd desktop
pnpm install
pnpm dev
```

The Electron app is a third client of the same gateway. It does not embed `AgentRuntime`. See [Desktop](docs/desktop.md).

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

Documented in [Production](docs/production.md) and [CLI](docs/cli.md). Notably: process-local rate limits, local/PV artifacts (not object storage), Playwright off unless isolated, no silent model failover. Run admission is global when Redis is available. A dead worker's run becomes `interrupted` and is not replayed. The CLI gateway client does not honor ambient `HTTP(S)_PROXY`, so bearer tokens are not forwarded to an implicit proxy. Closing a client does not cancel a run.

## Documentation

- [Production](docs/production.md)
- [Model gateway](docs/models.md)
- [HLD](docs/hld.md) / [LLD](docs/lld.md)
- [CLI](docs/cli.md) / [VS Code](docs/vscode.md) / [Desktop](docs/desktop.md)
- [Web research](docs/web_research.md)

## License

MIT. See [LICENSE](LICENSE).
