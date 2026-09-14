# Web Research & Content Extraction

 production-grade, self-hosted web research capability for ByteBuddhi.

## Why it exists

Agents need current public-web information without depending on a proprietary search SaaS, without treating web pages as trusted instructions, and without opening an SSRF path into the local network. Web research is a first-class ByteBuddhi capability: search, fetch, extract, optionally render, bound, artifact-store, and return a structured preview.

This is **not** a generic browser-automation or file-download system.

## Responsibility

```text
AgentRuntime
    → ToolExecutor
        → ToolPolicyEngine
            → web_research tool
                → WebResearchService
                    → WebSearchProvider / WebFetcher / WebRenderer
```

`WebResearchService` owns orchestration. The tool is a thin capability wrapper. `AgentRuntime` has no `web_research` special case.

## Ports (application-owned)

| Port | Contract | Infrastructure adapter |
|---|---|---|
| `WebSearchProvider` | `search(SearchRequest) → SearchResponse` | `DuckDuckGoSearchProvider` (HTML endpoint) |
| `WebFetcher` | `fetch(FetchRequest) → FetchedDocument` | `HttpxWebFetcher` |
| `WebRenderer` | `render(RenderRequest) → RenderedDocument` | `PlaywrightWebRenderer` or `NoOpWebRenderer` |

Application code never imports DuckDuckGo, httpx, or Playwright types. Provider replacement does not change AgentRuntime, ToolExecutor, CLI, or VS Code clients.

## Search provider abstraction

The first adapter talks to DuckDuckGo's public HTML endpoint. Configuration (`WEB_SEARCH_PROVIDER`, `WEB_SEARCH_ENDPOINT`, timeouts, User-Agent) lives in infrastructure settings. The agent only sees a `web_research` capability.

**Historical note — Tavily removal:** The proprietary Tavily SDK, `TavilySearchService`, `TAVILY_API_KEY`, and all executable/configuration references were removed. Search is no longer a vendor-specific integration. Do not reintroduce that SDK.

## Fetch pipeline

1. Validate the untrusted URL (`UrlSafetyPolicy`).
2. HTTP GET with a controlled header set (`User-Agent`, `Accept`, `Accept-Language` only).
3. Do **not** follow redirects automatically. Each `Location` is resolved and re-validated.
4. Reject unsupported content types (non-textual binary).
5. Stream the body and abort when `max_response_bytes` is exceeded (including when `Content-Length` already exceeds the limit).
6. Decode with the declared charset, replacing malformed bytes.

`ExternalHttpClient` remains the connector HTTP client (GitHub, etc.). It is not used for untrusted page fetch because it maps API status codes, reads the full body before bounding, and has no SSRF/redirect policy.

## SSRF and redirect policy

Untrusted URL → parse → scheme (`http`/`https` only) → hostname checks → DNS resolution → IP classification → request → validate every redirect target.

Blocked: localhost, loopback (`127.0.0.0/8`, `::1`), RFC1918, link-local (including `169.254.169.254`), unspecified, multicast, reserved, CGNAT (`100.64.0.0/10`), known metadata hostnames, URLs with embedded credentials, decimal IPv4 encodings of blocked addresses.

**DNS-rebinding limitation:** the policy resolves and inspects addresses *before* httpx connects. The HTTP library may resolve the hostname again. That race is not a perfect guarantee. Redirect targets are always re-validated. IP literals are classified without DNS.

`allowlisted_hosts` exists only so local tests can use loopback fixtures. Production settings must leave it empty.

## Content extraction

Stdlib `html.parser` (no BeautifulSoup in the application layer):

- Drops `script`, `style`, `nav`, `footer`, tracking-like chrome.
- Prefers `<article>` / `<main>` when present.
- Emits markdown-like headings, lists, tables, code fences, and links.

Limitations: layout-heavy sites, nested widgets, and JS-only pages may extract poorly until the renderer fallback runs. Extraction is heuristic, not a readability oracle.

## Playwright fallback

Used only when HTTP extraction yields too little text **and** `WEB_RENDER_ENABLED=true`.

- One shared browser, bounded concurrent pages.
- Same URL policy on the initial URL, `page.url` after navigation, and subresource `route` filters.
- Downloads disabled; extra browser features turned off.
- Optional extra: `uv sync --extra web-render` and `playwright install chromium`.

Real Chromium security tests live in `tests/integration/web/test_playwright_browser_security.py`. They are environment-dependent: if Playwright or Chromium is missing they are skipped and must be reported as **NOT EXECUTED -- browser runtime unavailable**, not as a pass.

This is not unrestricted browsing or a crawl engine.

## ArtifactStore integration

Large extracted markdown is stored via the existing `ArtifactStore` under the trusted `project_id` from `ExecutionContext` (projected through `ToolExecutionContext`). The model receives title, URL, bounded preview, provenance, and `artifact_id` — not the full document.

Project A cannot read Project B's artifacts. Model-supplied `user_id` / `project_id` / `workspace` arguments are ignored.

## Trust boundary

```text
SYSTEM / APPLICATION INSTRUCTIONS
        ≠
USER INPUT
        ≠
EXTERNAL WEB CONTENT
```

Web pages are untrusted data. Tool output includes an explicit notice. Page text cannot change system prompts, tool authorization, credentials, `ExecutionContext`, identity, workspace, or policy.

## Ordering and deduplication

Results are ordered by search rank, then original result order — never by fetch completion order. URLs are deduplicated by scheme, host, default port, path, and query; fragments are dropped. Distinct paths are not merged.

## Limits (trusted configuration)

Defaults (overridable via environment, never by the model):

| Setting | Default |
|---|---|
| `WEB_SEARCH_MAX_RESULTS` | 5 |
| `WEB_RESEARCH_MAX_PAGES` | 5 |
| `WEB_RESEARCH_MAX_CONCURRENT_FETCHES` | 4 |
| `WEB_FETCH_MAX_RESPONSE_BYTES` | 1_000_000 |
| `WEB_RESEARCH_MAX_EXTRACTED_CHARS` | 10_000 |
| `WEB_RESEARCH_MAX_TOTAL_CHARS` | 30_000 |
| `WEB_RESEARCH_MAX_DURATION_SECONDS` | 30 |

Retries are bounded and apply only to safe GET/search operations (connection failures, timeouts, 429 with `Retry-After`, selected 5xx).

## Robots.txt

Not implemented. ByteBuddhi web research is user-initiated, single-query fetching, not a crawler. Do not claim crawler compliance.

## Caching

No persistent web cache in this phase. Duplicate URLs are dropped within a single research operation.

## Observability

Spans: `web.research`, `web.search`, `web.fetch`, `web.extract`, `web.render` via application `Tracer`/`Meter` ports (no OpenTelemetry imports in application code).

Metric labels are low-cardinality (`provider_type`, `execution_status`, `extraction_method`, `content_type`). Full URLs, queries, artifact IDs, and raw HTML are not recorded.

## Resource lifecycle

HTTP sessions and optional browser processes are process-wide (documented singleton, same pattern as Redis) and closed on API shutdown. Timeouts and cancellation cancel outstanding fetch tasks.

## Known limitations

- DNS rebinding during the HTTP connect race is not perfectly eliminated. Pre-resolution plus address classification reduces SSRF risk; it is not a kernel-level or connect-time bind guarantee. Perfect DNS-rebinding protection is not claimed.
- Playwright in-navigation redirects are validated after navigation and via request routing; a tiny TOCTOU window remains.
- Chromium is launched with `--no-sandbox` for container compatibility. Production browser rendering (`WEB_RENDER_ENABLED=true`) requires a dedicated isolated container/VM; this is not a kernel sandbox. Keep rendering disabled unless that isolation exists.
- DuckDuckGo HTML markup can change; swap the adapter without touching application ports.
- JS rendering requires the optional `web-render` extra and installed Chromium. Real Chromium security tests skip when the browser is unavailable.
- robots.txt is not fetched.
- No authenticated fetching, cookie injection, or arbitrary file download.
