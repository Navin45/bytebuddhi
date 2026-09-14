# CLI

The ByteBuddhi CLI is a **thin terminal interface** over the same application path used by the REST API. It is not a second agent runtime, policy engine, workspace resolver, or persistence system.

```text
CLI commands
  → ExecuteTaskUseCase
  → trusted ExecutionContext
  → AgentRuntime / MultiAgentOrchestrator
  → ToolExecutor / ToolPolicyEngine
```

Local mode invokes use cases in-process. It does not proxy through FastAPI/HTTP.

## Installation

```bash
uv sync
bytebuddhi --help
bytebuddhi --version
```

The executable is installed from `[project.scripts]` as `bytebuddhi = app.interfaces.cli.main:main`.

## Authentication

There is no second auth system. The CLI authenticates a **local trusted principal** that must already exist in the application user store:

1. `--user-id <uuid>`
2. else `BYTEBUDDHI_USER_ID`
3. else `User.id` from `bytebuddhi login` (`~/.bytebuddhi/credentials.json`)

Unknown or inactive users exit with code `3`. The prompt cannot supply `user_id`, `project_id`, or workspace identity.

`bytebuddhi login --provider google` or `--provider github` opens the ByteBuddhi API OAuth URL in a browser. After the backend callback, paste the one-time code (`--code` or stdin). The CLI stores ByteBuddhi JWTs only; it never embeds Google/GitHub client secrets. `bytebuddhi logout` deletes the local credential file. Expired stored tokens require `bytebuddhi login` again.

`run` / `chat` still execute in-process through `ExecuteTaskUseCase` using that `User.id`. They do not send Google or GitHub tokens to the runtime. See [Authentication](authentication.md).

## Project and workspace selection

| Selector | Behavior |
|---|---|
| `--project <uuid>` | Authorized project. `WorkspaceResolutionService` resolves the workspace. |
| `BYTEBUDDHI_PROJECT_ID` | Same as `--project` when the flag is omitted. |
| `--cwd <path>` | **Explicit** local path. Only when `WORKSPACE_MODE=local`, and only if that path is an **owned project's `local_path`**. |
| omitted | Application scratch workspace for the user (`scratch_<user>`). The CLI never silently uses `.`. |

`--project` and `--cwd` together are a usage error.

`--cwd .` is allowed only as an explicit opt-in, still authorized by the application layer.

Managed/production mode (`WORKSPACE_MODE=managed`) rejects `--cwd`.

## Commands

### `bytebuddhi run`

Primary syntax:

```bash
bytebuddhi run "Explain this repository"
bytebuddhi run --prompt "Explain this repository"
bytebuddhi run --project <uuid> --json "Run the tests and summarize failures"
bytebuddhi run --provider openai --model gpt-4-turbo-preview "Summarize this module"
```

Do not pass both a positional prompt and `--prompt`.

### `bytebuddhi chat`

Interactive loop. Each turn calls `ExecuteTaskUseCase` and reuses `conversation_id` from the application result. Type `quit` / `:quit` to exit.

Non-interactive: pipe lines on stdin. JSON/quiet modes do not print a prompt.

### `bytebuddhi project list` / `bytebuddhi project show <id>`

Read-only inspection of projects owned by the authenticated user. Another user's project is denied.

### `bytebuddhi models`

Lists catalog models (provider, id, availability). Does not print keys or endpoints.

### `bytebuddhi login` / `bytebuddhi logout`

```bash
bytebuddhi login --provider google
bytebuddhi login --provider github --code <one-time-code>
bytebuddhi logout
```

Browser sign-in against the API (`BYTEBUDDHI_API_URL`, default `http://127.0.0.1:8000`). Credentials are written to `BYTEBUDDHI_CONFIG_DIR` or `~/.bytebuddhi/credentials.json`.

### `bytebuddhi health`

Read-only database ping. Does not start an agent run.

Artifact get/list commands are not included. The CLI prints artifact **references** when the runtime archives large output; it does not dump artifact bodies.

There is no `bytebuddhi exec` shell command.

## Output modes

Precedence: `--json` / `--output` → `BYTEBUDDHI_OUTPUT` → `human`.

| Mode | stdout | stderr |
|---|---|---|
| human | Result text | Progress, errors |
| json | One JSON object | Progress (unless `--quiet`), errors |

JSON is deterministic (`sort_keys=True`) and has no ANSI. Example success envelope:

```json
{
  "answer": "...",
  "artifacts": [],
  "conversation_id": "...",
  "errors": [],
  "run_id": "...",
  "status": "success",
  "tools": [],
  "workspace_id": "..."
}
```

`--quiet` suppresses progress. `--debug` increases logging on stderr only. Debug mode does **not** disable authorization, workspace containment, tool policy, SSRF protection, artifact ownership, or credential isolation.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Execution failure |
| 2 | Usage / argument error |
| 3 | Authentication / authorization failure |
| 4 | Workspace / project failure |
| 5 | Timeout / cancellation |
| 6 | Configuration failure |

## Cancellation

Ctrl+C / SIGINT and SIGTERM cancel the asyncio task wrapping `ExecuteTaskUseCase.execute()`. The process waits for application cleanup (DB session, HTTP client, web-research resources, Redis if started) before exiting with code `5`.

The CLI does not independently override tool, agent, orchestration, or web-research timeouts.

## Configuration

Uses the existing `Settings` model (`.env` / environment). The CLI does not add `CLISettings`.

Useful variables: `BYTEBUDDHI_USER_ID`, `BYTEBUDDHI_PROJECT_ID`, `BYTEBUDDHI_API_URL`, `BYTEBUDDHI_CONFIG_DIR`, `BYTEBUDDHI_OUTPUT`, `BYTEBUDDHI_QUIET`, plus existing `WORKSPACE_MODE`, `WORKSPACE_ROOT`, `DATABASE_URL`, provider keys.

Do not print JWT, API keys, passwords, or tokens. There is no `bytebuddhi config` dump command.

## Security notes

- The CLI is an interface over the same trusted application runtime as the API.
- It does not bypass project authorization, tool policy, workspace containment, artifact ownership, or execution identity.
- Filesystem paths from `--cwd` are resolved to an owned project, then `WorkspaceResolutionService` enforces containment.
- Web research runs only through the existing `web_research` tool. The CLI does not execute commands suggested by web content and does not print raw HTML.
- Observability uses the application tracer/meter. There is no CLI-specific telemetry backend.

## CI example

```bash
bytebuddhi run --json --quiet --user-id "$BYTEBUDDHI_USER_ID" --project "$BYTEBUDDHI_PROJECT_ID" "Summarize failing tests" > result.json
```
