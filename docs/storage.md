# Storage

Application code depends on repository ports: projects, conversations,
messages, runs, events, and memory. The composition root selects an
implementation. Use cases do not branch on the database.

## Server

PostgreSQL stores users, projects, conversations, messages, files, code chunks,
embeddings, and agent runs. Redis provides the run queue, admission, live
fan-out, and cancellation coordination for multiple workers. Workers take
leases. A reaper interrupts runs whose leases expire. Alembic migrations own
this schema, including PostgreSQL-specific types such as `pgvector`.

Health for this profile reports `database=postgres` and `redis=ready` when
Redis coordination is required. A missing Redis is unhealthy only in that mode.

## Standalone

SQLite schema version 1 is independent of the Alembic history. Identifiers and
timestamps are text. JSON columns are text. The database uses WAL and
`BEGIN IMMEDIATE` transactions. There is no `SELECT FOR UPDATE` and no
`SKIP LOCKED`. One process-local worker owns runs.

Code embeddings are JSON vectors scored with in-process cosine similarity.
That is not `pgvector`. An empty query embedding is an error. Memory remains
in the same local database through the existing SQLite memory store. Standalone
memory is not written to PostgreSQL.

Health reports `database=sqlite`, `redis=not_required`, and `execution=ready`.
Redis is not marked unhealthy because this profile does not use it.

## Remote

`BYTEBUDDHI_GATEWAY_URL` points the client at a gateway. The client still uses
REST and WebSocket. The remote gateway's own profile decides whether that
gateway uses PostgreSQL or SQLite.

## Isolation

| | Standalone | Server |
|---|---|---|
| PostgreSQL client | not created | required |
| Redis client | not created | required when coordination is enabled |
| Database file | config directory `data/bytebuddhi.db` | not used |
| Worker | started by the local gateway | separate worker processes |

Making the SQLite path unreadable does not change server mode. Stopping
PostgreSQL and Redis does not stop a gateway that was started with
`--profile standalone`.
