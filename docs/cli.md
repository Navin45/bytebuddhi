# CLI

The ByteBuddhi CLI and terminal interface are **gateway clients** by default. They are not a second agent runtime, policy engine, workspace resolver, or persistence system.

Phase 1 establishes the transport boundary:

```text
CLI
  → GatewayClient
  → FastAPI gateway
  → ExecuteTaskUseCase
  → trusted ExecutionContext
  → AgentRuntime
```

Future TUI, GUI, and editor clients can use the same HTTP contract: user, project, conversation, run, message, model, and cancellation. The API does not speak in terminal or argparse concepts.

`--embedded` keeps the previous in-process path for `bytebuddhi run`. It is explicit. If the gateway cannot be reached, the CLI stops with an error. It does not switch to embedded mode. `bytebuddhi tui` has no embedded path.

## Installation

```bash
uv sync
bytebuddhi --help
bytebuddhi --version
```

The executable is installed from `[project.scripts]` as `bytebuddhi = app.interfaces.cli.main:main`.

## Local gateway

`bytebuddhi serve` runs the **existing** FastAPI application in the foreground. It uses the application lifespan, middleware, auth, routes, logging, and health checks. It binds one process, without reload.

```bash
bytebuddhi serve
bytebuddhi serve --host 127.0.0.1 --port 8765
```

Defaults:

| Setting | Default | Override |
|---|---|---|
| Host | `127.0.0.1` | `--host` or `BYTEBUDDHI_GATEWAY_HOST` |
| Port | `8765` | `--port` or `BYTEBUDDHI_GATEWAY_PORT` |

The local gateway binds to loopback unless you explicitly pass another host, including `0.0.0.0`. Production multi-worker Gunicorn is a separate entrypoint and is not used here.

Background lifecycle:

```bash
bytebuddhi gateway start
bytebuddhi gateway status
bytebuddhi gateway stop
bytebuddhi gateway restart
```

`start` waits until `GET /api/v1/health/ready` succeeds or the startup timeout expires. A live process is not the same thing as ready. `status` reports running state, PID when known, URL, readiness, version, and uptime. Runtime metadata is stored under `BYTEBUDDHI_CONFIG_DIR` or `~/.bytebuddhi/` (`gateway.json`). It contains no tokens.

`stop` asks that process to shut down, waits, then terminates it if needed. It does not kill an unrelated process that happens to be listening on the port. A stale PID file is discarded when the process is gone.

Ctrl+C during `bytebuddhi run` cancels the client request. It does not stop a gateway that `gateway start` or a previous command started. Ctrl+C during `bytebuddhi serve` stops that foreground process.

Normal `bytebuddhi run` starts the local gateway when the resolved URL is that local gateway and `--no-start-gateway` was not passed. It never auto-starts a remote URL, including an explicit `BYTEBUDDHI_GATEWAY_URL` that is not the local gateway.

## Gateway URL

One resolver is shared by the CLI, login, and the gateway manager:

```text
explicit --gateway-url or login --api-url
    > BYTEBUDDHI_GATEWAY_URL
    > BYTEBUDDHI_API_URL
    > http://127.0.0.1:<BYTEBUDDHI_GATEWAY_PORT or 8765>
```

`bytebuddhi login --api-url` still overrides the environment. The value is an origin with no path, query, fragment, or embedded credentials. Example: `http://127.0.0.1:8765`.

`--cwd` is sent only to the local gateway, which resolves it with `ResolveProjectByLocalPathUseCase` on the gateway host. A remote URL rejects `--cwd`. `--project` works for local and remote gateways. The application layer still authorizes the project.

## Authentication

Gateway mode sends `Authorization: Bearer <access_token>` from `~/.bytebuddhi/credentials.json`. The server's `get_current_user()` check is the authority. The client does not verify the JWT locally, does not send a user id as authorization, and does not contain `JWT_SECRET_KEY`.

1. `bytebuddhi login` (Google or GitHub) stores the ByteBuddhi access and refresh tokens.
2. Commands that need auth fail with exit code `3` when the token is missing or the gateway returns 401/403.
3. `bytebuddhi logout` deletes the credential file.

`--user-id` and `BYTEBUDDHI_USER_ID` apply to `--embedded` only. They are not sent to the gateway.

The credential file is separate from endpoint configuration. It is still plaintext JSON with mode `0600` where the platform allows it. OS keyring storage is a later follow-up. Tokens are not written to logs, process arguments, or gateway runtime metadata.

## Embedded mode

```bash
bytebuddhi run --embedded "Explain this repository"
BYTEBUDDHI_EXECUTION_MODE=embedded bytebuddhi run "Explain this repository"
```

`--gateway` forces gateway mode when the environment variable is `embedded`. Gateway mode remains the default. Embedded mode loads application use cases in-process, including `ExecuteTaskUseCase`. It is for development and tests.

## Commands

### `bytebuddhi run`

```bash
bytebuddhi run "Explain this repository"
bytebuddhi run --prompt "Explain this repository"
bytebuddhi run --project <uuid> --json "Run the tests and summarize failures"
bytebuddhi run --provider openai --model gpt-4-turbo-preview "Summarize this module"
bytebuddhi run --no-start-gateway "Explain this repository"
bytebuddhi run --gateway-url https://gateway.example "Explain this repository"
bytebuddhi run --embedded --user-id <uuid> "Explain this repository"
```

Gateway mode calls `POST /api/v1/runs` once, with an `Idempotency-Key`. That request is not retried. The response is `202` and `status: queued`. The CLI then opens `WS /api/v1/runs/{run_id}/stream` and renders events until `run_completed`, `run_failed`, or `run_cancelled`. A dropped socket is retried a few times from the last sequence. It does not create a second run, and it does not cancel the run.

Do not pass both a positional prompt and `--prompt`.

### `bytebuddhi chat`

Interactive loop. Each turn calls the same run API and reuses `conversation_id`. Type `quit` / `:quit` to exit.

Non-interactive: pipe lines on stdin. JSON/quiet modes do not print a prompt.

### `bytebuddhi tui`

Opens the Textual terminal client. See [Terminal interface](#terminal-interface). It is gateway-only: no `--embedded`, no second runtime, and no local conversation database.

### `bytebuddhi project list` / `bytebuddhi project show <id>`

Read-only inspection of projects owned by the authenticated user. Another user's project is denied by the API.

### `bytebuddhi models`

Lists catalog models from `GET /api/v1/models`. Requires a bearer token in gateway mode. Does not print keys or endpoints.

### `bytebuddhi health`

Reads `/api/v1/health/live` and `/api/v1/health/ready`. Does not start an agent run. Exit code `0` when readiness is `ready`.

### `bytebuddhi login` / `bytebuddhi logout`

```bash
bytebuddhi login --provider google
bytebuddhi login --provider github --code <one-time-code>
bytebuddhi login --api-url http://127.0.0.1:8765
bytebuddhi logout
```

### `bytebuddhi serve` and `bytebuddhi gateway`

See [Local gateway](#local-gateway).

Artifact get/list commands are not included. Gateway events carry artifact ids and short previews, not artifact bodies. Embedded mode can still print web-research previews from in-process tool results.

There is no `bytebuddhi exec` shell command.

## Output modes

Precedence: `--json` / `--output` → `BYTEBUDDHI_OUTPUT` → `human`.

| Mode | stdout | stderr |
|---|---|---|
| human | Assistant text as it arrives | Progress, tool names, errors, gateway logs |
| json | One JSON object per line (JSONL) | Errors |

JSONL is deterministic (`sort_keys=True`) and has no ANSI. Each line is the public event envelope:

```json
{"created_at":"...","data":{"delta":"Hello"},"event_id":"...","run_id":"...","schema_version":1,"sequence":3,"type":"assistant_delta"}
{"created_at":"...","data":{"assistant_message_id":"...","conversation_id":"...","duration_ms":12},"event_id":"...","run_id":"...","schema_version":1,"sequence":4,"type":"run_completed"}
```

`assistant_message_id` is the persisted assistant message. It is not the conversation id. Embedded `--json` still prints the single in-process success envelope. Gateway `--json` does not.

`--quiet` suppresses progress. `--debug` increases logging on stderr only. Debug mode does **not** disable authorization, workspace containment, tool policy, SSRF protection, artifact ownership, or credential isolation. It also does not print access tokens.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Execution failure, or the gateway could not be reached |
| 2 | Usage / argument error |
| 3 | Authentication / authorization failure |
| 4 | Workspace / project failure, including `--cwd` against a remote gateway |
| 5 | Timeout / cancellation |
| 6 | Configuration failure, including a port owned by another program |

## Cancellation

Ctrl+C cancels the run. The CLI calls `POST /api/v1/runs/{run_id}/cancel` and exits `5`. That request is explicit. Closing the terminal's network connection, or a WebSocket disconnect, does not cancel the run. The agent keeps working. Reconnect with the same run and `after_sequence` set to the last sequence you have.

`run_cancel_requested` means the cancel was accepted. `run_cancelled` means execution stopped. A completed run returns `409` with `RUN_ALREADY_COMPLETED`. `POST /api/v1/agent/runs/{run_id}/cancel` remains for the older chat path.

For a foreground `bytebuddhi serve`, Ctrl+C stops that process. It does not stop a gateway started separately.

The CLI does not independently override tool, agent, orchestration, or web-research timeouts. Gateway HTTP calls use finite connect, API, agent, and stream timeouts. Agent creation is not retried. Stream reconnects are bounded.

## Asynchronous runs

```text
CLI
  ↓
POST /api/v1/runs          → 202 {run_id, conversation_id, status: queued}
  ↓
WS /api/v1/runs/{id}/stream?after_sequence=0
  ↓
PostgreSQL event store     Redis pub/sub fanout
```

PostgreSQL is the durable source of truth. Redis only notifies live subscribers. If Redis is down, the event is still stored. A client recovers it with `GET /api/v1/runs/{run_id}/events?after_sequence=N` or by reconnecting the socket.

`after_sequence` means strictly greater than that sequence. `after_sequence=42` sends 43, 44, and so on. Sequences start at 1 and never use timestamps for order.

A slow client is disconnected (`1013`). Durable events stay in PostgreSQL. The client reconnects with its last sequence.

Event types: `run_queued`, `run_started`, `assistant_delta`, `tool_started`, `tool_completed`, `message_created`, `run_completed`, `run_failed`, `run_cancel_requested`, `run_cancelled`, `run_interrupted`. The envelope is `event_id`, `run_id`, `sequence`, `type`, `schema_version` (1), `created_at`, `data`.

Same bearer token as REST, in the `Authorization` header. The header is not logged. Another user's run looks the same as a missing run (`404` / socket close `4404`).

`--embedded` does not use this socket. It still executes in-process. A gateway failure does not fall back to embedded mode.

Runs carry a worker lease. The owner renews it about every 15 seconds (`BYTEBUDDHI_RUN_HEARTBEAT_SECONDS`). The lease expires after `BYTEBUDDHI_RUN_LEASE_TIMEOUT_SECONDS` (default 120) without a renewal. Expiry means the worker is gone, not that the task ran too long. One reaper, coordinated with a Postgres advisory lock, marks that run `interrupted` and appends `run_interrupted`. It does not replay the agent. Tool side effects may already have happened.

`BYTEBUDDHI_MAX_ACTIVE_RUNS` (default 20) is a global limit acquired by the worker that executes the run. With Redis, the slot expires if that worker dies. Without Redis, admission is process-local and readiness reports `execution: degraded`. A Redis outage while Redis is required fails readiness closed: queued runs stay in PostgreSQL and are not executed until admission works again.

## Terminal interface

```text
Textual TUI
    ↓
GatewayClient
    ↓
FastAPI
    ↓
Run protocol
    ↓
AgentRuntime
```

```bash
bytebuddhi tui
bytebuddhi tui --project "$BYTEBUDDHI_PROJECT_ID"
BYTEBUDDHI_GATEWAY_URL=https://gateway.example bytebuddhi tui
bytebuddhi tui --no-start-gateway
```

`tui` is gateway-only. It does not accept `--embedded` and it does not call `AgentRuntime`. URL precedence is the same resolver used by `run` and `login`. When the resolved URL is the local loopback gateway, `tui` uses `GatewayManager` to start it and wait until ready. A remote URL never starts a local gateway. `--no-start-gateway` skips that start and fails if the gateway is not already reachable.

Authentication uses the existing credential file. A missing or rejected token tells you to run `bytebuddhi login`. The TUI does not start its own OAuth flow, and it never prints the access token.

The server is authoritative for projects, conversations, messages, and models. The TUI loads them through `GatewayClient` and keeps only an in-memory projection. `/clear` reloads history. It does not delete server state.

| Key | Action |
|---|---|
| Enter | Send the composer as one run |
| Shift+Enter | Insert a newline |
| Esc | `POST /api/v1/runs/{run_id}/cancel` for the active run |
| ? | Help |
| Ctrl+Q | Quit without cancelling the run |
| `/help` `/new` `/projects` `/models` `/clear` `/quit` | The same actions as the keys and pickers |

Enter does nothing while a run is queued, running, or waiting for cancellation, so a repeated Enter cannot create a second run. Esc does not mark the run cancelled when the HTTP call returns. The status stays locked until `run_cancelled`, `run_completed`, `run_failed`, or `run_interrupted`.

A WebSocket drop shows `RECONNECTING 1/3`, then `2/3`, then `3/3`. Each attempt replays `GET /api/v1/runs/{run_id}/events?after_sequence=<last>` and resumes the same `run_id`. It does not call `POST /api/v1/runs` again. After three failed attempts the status is `DISCONNECTED`. A sequence gap uses that same replay and applies the missing event before later ones.

Closing the TUI closes the socket and HTTP client. It does not cancel the run. The gateway keeps executing. Open `bytebuddhi tui` again to load the conversation from the server.

`run_interrupted` is a distinct terminal state (`INTERRUPTED`). It means the worker stopped and the agent was not replayed. The composer unlocks.

The layout hides the sidebar when the terminal is narrower than 72 columns. Status words stay readable without color. The TUI needs an interactive terminal; a pipe exits with a usage error before Textual starts.

## Configuration

Uses the existing `Settings` model (`.env` / environment) on the server. The CLI adds gateway endpoint variables, not a second settings model for agent policy.

Useful variables: `BYTEBUDDHI_GATEWAY_URL`, `BYTEBUDDHI_API_URL`, `BYTEBUDDHI_GATEWAY_HOST`, `BYTEBUDDHI_GATEWAY_PORT`, `BYTEBUDDHI_GATEWAY_START_TIMEOUT`, `BYTEBUDDHI_EXECUTION_MODE`, `BYTEBUDDHI_USER_ID` (embedded only), `BYTEBUDDHI_PROJECT_ID`, `BYTEBUDDHI_CONFIG_DIR`, `BYTEBUDDHI_OUTPUT`, `BYTEBUDDHI_QUIET`, plus existing `WORKSPACE_MODE`, `WORKSPACE_ROOT`, `DATABASE_URL`, provider keys.

Do not print JWT, API keys, passwords, or tokens. There is no `bytebuddhi config` dump command.

The gateway client connects directly. It does not trust `HTTP_PROXY` / `HTTPS_PROXY`, so a bearer token is not sent to an ambient proxy.

## Security notes

- Gateway mode does not bypass project authorization, tool policy, workspace containment, artifact ownership, or execution identity. Those stay in the application layer.
- Filesystem paths from `--cwd` are accepted only for the local gateway, then `ResolveProjectByLocalPathUseCase` and `WorkspaceResolutionService` enforce ownership and containment.
- Web research runs only through the existing `web_research` tool.
- Observability uses the application logger. Gateway lifecycle events include host, port, duration, status, and request id. They do not include tokens or `Authorization` headers.

## CI example

Gateway mode, after `bytebuddhi login` or with a credential file already present:

```bash
bytebuddhi run --json --quiet --no-start-gateway --gateway-url "$BYTEBUDDHI_GATEWAY_URL" "Summarize failing tests"
```

Each stdout line is one event. Exit `0` after `run_completed`.

In-process mode for a trusted local principal still prints one JSON object:

```bash
bytebuddhi run --embedded --json --quiet --user-id "$BYTEBUDDHI_USER_ID" --project "$BYTEBUDDHI_PROJECT_ID" "Summarize failing tests" > result.json
```

## Not in this phase

Desktop GUI, Electron, offline SQLite profiles, OS keyring storage, and release automation are later phases. Those clients can consume the same run and event protocol without another agent runtime. A dead worker is detected and the run becomes `interrupted`; the agent is not replayed. The terminal interface is the Textual client documented above.
