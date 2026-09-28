# Standalone profile

ByteBuddhi has two local execution profiles. The profile chooses storage and
the worker. It does not choose the language model.

| Profile | Storage | Coordination | How to select it |
|---|---|---|---|
| `server` | PostgreSQL | Redis, leases, admission, reaper | Default for existing installations |
| `standalone` | SQLite | One local worker and an in-process event bus | `bytebuddhi --profile standalone` |

A remote gateway is an endpoint (`BYTEBUDDHI_GATEWAY_URL`), not a profile.
Standalone mode does not open PostgreSQL or Redis. Server mode does not read
the standalone database.

## Select a profile

Resolution order:

1. `bytebuddhi --profile server|standalone`
2. `BYTEBUDDHI_PROFILE`
3. Persisted `profile` in the local config file
4. `server`

`bytebuddhi profile show` prints the active profile. `bytebuddhi profile set standalone`
stores the choice. Existing server installations stay on PostgreSQL until that
choice is made. Startup does not copy data.

## What standalone runs

```
bytebuddhi
  local gateway
    SQLite database
    local queue
    one local worker
    ExecuteTaskUseCase
    AgentRuntime
```

The gateway starts the worker and stops it on shutdown. A separate `worker`
process is not required. Run states remain `queued`, `running`, `cancelling`,
`completed`, `failed`, `cancelled`, and `interrupted`. Cancellation still uses
`POST /api/v1/runs/{id}/cancel` and records `run_cancel_requested` before
`run_cancelled`.

Events are stored in SQLite and published on the in-process bus. The REST event
page and WebSocket stream are the same APIs the desktop, TUI, and CLI already
use. After a gateway restart, completed events replay from SQLite. A run that
was waiting for tool approval is marked `interrupted`. The tool is not treated
as approved, and a new approval is required before it runs again.

## Local storage is not local inference

The standalone database holds projects, conversations, messages, runs, events,
and local memory. Model calls still use the configured provider. A standalone
install can use a cloud model. Selecting a local model is a separate setting.

## Data location

The database is `<config directory>/data/bytebuddhi.db`. The config directory
comes from the existing platform path (`BYTEBUDDHI_CONFIG_DIR`, otherwise the
ByteBuddhi config directory). `BYTEBUDDHI_SQLITE_PATH` overrides the file.
The database is not created in the repository or the project workspace.
Artifacts stay as files under the config directory `artifacts` folder. The
database stores references, not large blobs.

The file mode is restricted to the current user where the operating system
allows it. Doctor and support bundles do not include the database.

## Commands

```
bytebuddhi --profile standalone
bytebuddhi profile show
bytebuddhi profile set standalone
bytebuddhi data backup backup.zip
bytebuddhi data backup backup.zip --include-artifacts
bytebuddhi data migrate --to-standalone --source postgresql+asyncpg://...
bytebuddhi doctor
```

`data migrate` is explicit. It requires `--to-standalone` and a source URL.
It refuses to replace an existing standalone database unless `--yes` is passed.
Embeddings are not copied from PostgreSQL; the report records that count as
zero. Restore a backup by stopping ByteBuddhi and replacing `bytebuddhi.db`
with the copy inside the zip. Credentials are not in the archive.

`bytebuddhi doctor` reports the profile, storage, database path, that Redis is
not used, and the local execution mode. It runs `PRAGMA integrity_check` and
does not delete a corrupt database.
