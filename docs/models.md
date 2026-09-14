# Model gateway

ByteBuddhi inference goes through one application boundary: `ModelGateway`.

```text
ExecuteTaskUseCase
        ↓
AgentRuntime
        ↓
RoutingModelGateway
        ↓
catalog authorize → provider adapter → LLM
        ↓
normalized ModelResponse
```

`AgentRuntime` does not branch on provider names. Adding a provider is adapter registration plus catalog configuration.

## Defaults vs selection

`DEFAULT_MODEL_PROVIDER` and `DEFAULT_MODEL_NAME` are the **default** only. A request may select any **enabled, available** catalog model. A failed selection is not rewritten to the default.

Credentials stay on the server (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, compatible key). They are never accepted from API/CLI/VS Code payloads, `ExecutionContext`, logs, or telemetry.

There is no user BYOK (bring-your-own-key) system.

## Catalog

`GET /api/v1/models` (JWT) returns:

- `provider`, `model`, `display_name`, `capabilities`, `available`
- configured default

It never returns API keys, authorization headers, or operator endpoint URLs.

Availability:

| State | Meaning |
|---|---|
| available | Provider enabled and credentials present |
| unavailable | Listed but not usable (missing key) |
| absent | Provider not enabled / not registered |

## OpenAI-compatible endpoints

Set by the **operator**, not the user:

```env
OPENAI_COMPATIBLE_ENABLED=true
OPENAI_COMPATIBLE_PROVIDER_ID=local
OPENAI_COMPATIBLE_BASE_URL=http://llm-gateway.internal/v1
OPENAI_COMPATIBLE_API_KEY=...
OPENAI_COMPATIBLE_MODELS=my-model
```

A request cannot pass `https://attacker.example` as a provider or base URL.

## Adding an adapter

1. Implement `ModelGateway` (`generate` / `stream`) in `app/infrastructure/llm/`.
2. Register it in `build_provider_registry()`.
3. Add catalog descriptors in `build_model_catalog()`.
4. Do not change `AgentRuntime`.

Built-in adapters: OpenAI, Anthropic, OpenAI-compatible. Other vendors can be added the same way or reached through a compatible gateway.

## Clients

- API: `MessageCreateRequest.model = { "provider", "model" }`
- CLI: `bytebuddhi run --provider ... --model ...` and `bytebuddhi models`
- VS Code: **ByteBuddhi: Select Model** loads the catalog

## Failures

Provider errors are normalized (`authentication_failure`, `rate_limited`, `timeout`, `model_unavailable`, `provider_unavailable`, `invalid_request`, `response_malformed`). There is no automatic failover. LLM requests remain bounded by `LLM_REQUEST_TIMEOUT_SECONDS` and the existing cancellation token.
