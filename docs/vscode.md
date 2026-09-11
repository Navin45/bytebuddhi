# Phase 9 — VS Code Extension

The ByteBuddhi VS Code extension is a **thin IDE client**. It talks to the existing HTTP API. It is not an agent runtime, tool executor, workspace authorizer, or second persistence/telemetry system.

```text
VS Code
  → JWT API client
  → POST /api/v1/chat/conversations/{id}/messages
  → ExecuteTaskUseCase
  → trusted ExecutionContext
  → AgentRuntime / MultiAgentOrchestrator
```

## Requirements

- VS Code **1.90+**
- A running ByteBuddhi API (`uv run uvicorn app.interfaces.api.main:app --host 127.0.0.1 --port 8000`)
- An existing user account (same JWT login as the REST API)

## Development setup

```bash
cd vscode-extension
npm install
npm run compile
npm run lint
npm test
```

Press **F5** on the `Run Extension` launch config in `vscode-extension/.vscode/launch.json` after `npm run compile`. The Extension Development Host loads `out/extension.js`.

## Authentication

**ByteBuddhi: Sign In** posts to `/api/v1/auth/login`. Access and refresh tokens are stored only in VS Code `SecretStorage`.

They are never written to `settings.json`, webview HTML, OutputChannel, or source.

**ByteBuddhi: Sign Out** deletes secrets and clears client conversation state.

## Configuration (non-secret)

| Setting | Default | Meaning |
|---|---|---|
| `bytebuddhi.serverUrl` | `http://127.0.0.1:8000` | API origin |
| `bytebuddhi.project` | empty | Optional project UUID sent as a *request*. The API still checks ownership. |

Workspace folder path is matched against `GET /api/v1/projects` `local_path` as a convenience. The extension never treats that match as authorization.

## Commands

| Command | Behavior |
|---|---|
| Sign In / Sign Out | JWT session in SecretStorage |
| Run Task | Prompt → `ExecuteTaskUseCase` via chat messages API |
| Open Chat | Focus the ByteBuddhi webview |
| Cancel Task | Abort the HTTP stream **and** `POST /api/v1/agent/runs/{run_id}/cancel` |
| Show Status | Read-only health + local UI status |

There is no artifact opener and no shell/exec command.

## Chat

The sidebar webview posts only `{ type, prompt? }`. The extension host validates messages and rejects identity, approval, and credential fields.

Optional editor **selection** (bounded to 8,000 characters) may be appended. The whole repository is never uploaded. File text is untrusted user content, not system instructions.

Closing the UI does **not** by itself mean the server cancelled the run. Disconnecting the SSE stream cancels the in-process execute task on the API worker. Prefer **Cancel Task** for an explicit application cancel.

## Cancellation

Shared application `CancellationToken` + process-local `RunCancellationRegistry`:

```text
VS Code Cancel
  → POST /api/v1/agent/runs/{run_id}/cancel (JWT user must own the run)
  → token + asyncio.Task cancel
  → ExecuteTaskUseCase / AgentRuntime / tools
```

Unknown or other-user run ids return 404 (no ownership oracle). The registry is **process-local** (one API worker), like the rate limiter.

The extension does **not** retry `sendMessage` after a network timeout (the server may already have started the run).

## Security notes

- The extension does not bypass project authorization, tool policy, workspace containment, or artifact ownership.
- Webview CSP: `default-src 'none'`, nonce scripts, no `unsafe-inline`, no `eval`.
- Model/web text is rendered with `textContent`, not HTML injection.
- No `child_process` / shell convenience commands.

## Troubleshooting

| Symptom | Check |
|---|---|
| Not signed in | Run Sign In; confirm API `/api/v1/health` |
| Authentication expired | Sign in again; refresh token is used once on 401 |
| Server unavailable | `bytebuddhi.serverUrl` and that uvicorn is listening |
| Wrong project | Set `bytebuddhi.project` or bind `local_path` on the project |
| Cancel 404 | Run already finished, or another worker owns the registry |
