# Anthropic — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

Anthropic is a foundation-model vendor whose Claude family (Opus / Sonnet /
Haiku) is consumed via the Messages API, billed per token with cache and batch
discounts. Costly's `anthropic_connector.py` pulls daily token rollups from
the Admin API `/v1/organizations/usage` endpoint using an Admin API key and
estimates cost using a built-in per-million price table. Current grade: **C+**
— the connector uses a stale / wrong endpoint path (`/usage` rather than the
current `/usage_report/messages` + `/cost_report`), ignores cache tiers and
service_tier, has no workspace or api-key dimension, and silently returns
`[]` when credentials are missing admin scope. This doc is the punch list.

## Pricing Model (from vendor)

Canonical source: <https://platform.claude.com/docs/en/about-claude/pricing>.
All prices USD per million tokens, standard service tier, list / non-batch.

| Model | Input | Output | Cache read (0.1×) | Cache write 5m (1.25×) | Cache write 1h (2.0×) |
|---|---|---|---|---|---|
| Claude Opus 4.7 (released 2026-04-16) | $15.00 | $75.00 | $1.50 | $18.75 | $30.00 |
| Claude Opus 4.6 | $15.00 | $75.00 | $1.50 | $18.75 | $30.00 |
| Claude Opus 4 | $15.00 | $75.00 | $1.50 | $18.75 | $30.00 |
| Claude Sonnet 4.7 | $3.00 | $15.00 | $0.30 | $3.75 | $6.00 |
| Claude Sonnet 4.6 | $3.00 | $15.00 | $0.30 | $3.75 | $6.00 |
| Claude Sonnet 4.5 | $3.00 | $15.00 | $0.30 | $3.75 | $6.00 |
| Claude Sonnet 4 | $3.00 | $15.00 | $0.30 | $3.75 | $6.00 |
| Claude Haiku 4.5 | $1.00 | $5.00 | $0.10 | $1.25 | $2.00 |
| Claude Haiku 4 | $1.00 | $5.00 | $0.10 | $1.25 | $2.00 |
| Claude Haiku 3.5 | $0.80 | $4.00 | $0.08 | $1.00 | $1.60 |
| Claude Haiku 3 | $0.25 | $1.25 | $0.025 | $0.3125 | $0.50 |
| Claude Opus 3.5 (legacy, deprecated) | $15.00 | $75.00 | $1.50 | $18.75 | $30.00 |
| Claude Sonnet 3.5 (legacy, deprecated) | $3.00 | $15.00 | $0.30 | $3.75 | $6.00 |

Pricing modifiers:

- **Batch API**: 50% flat discount on both input and output tokens. Best for
  offline classification, summarisation, embedding-style bulk jobs. Stacks
  with cache. Source: <https://www.finout.io/blog/anthropic-api-pricing>.
- **Prompt caching** (all models, 5m default TTL): writes are 1.25× input
  list, reads are 0.10× input list. Extended 1h TTL: writes are 2.0× input
  list (reads still 0.10× input). Source:
  <https://platform.claude.com/docs/en/build-with-claude/prompt-caching>.
- **Service tier** (`service_tier` field on request, echoed on response):
  `"standard"` (default), `"priority"` (capacity-reserved, higher base
  price), `"batch"` (async, 50% discount). Requests can set
  `service_tier: "auto"` to opt into priority routing when available.
  Source: <https://docs.anthropic.com/en/api/service-tiers>.
- **1M token context**: Opus 4.7, Opus 4.6, Sonnet 4.6 support a 1M context
  window at the same per-token rate as shorter contexts — no tier pricing.
- **Opus 4.7 tokenizer uplift**: metacto.com and evolink.ai report 1.0–1.35×
  denser tokenisation vs Opus 4.6 at the same character count — effective
  cost increases even at the same per-token rate. Source:
  <https://evolink.ai/blog/claude-api-pricing-guide-2026>.
- **Region pricing**: Anthropic's Messages API is priced uniformly in USD
  globally. Only the `inference_geo` routing label differs. Vertex-AI-hosted
  and Bedrock-hosted Claude bill via the host cloud (see `gemini.md` /
  AWS CUR respectively), _not_ via Anthropic.
- **Managed Agents** (launched 2025): meter + priority premium over raw
  Messages — still token-denominated but with additional per-agent-run
  overhead. Source:
  <https://www.finout.io/blog/anthropic-just-launched-managed-agents.-lets-talk-about-how-were-going-to-pay-for-this>.

## Billing / Usage Data Sources

### Primary

**Anthropic Admin API — Usage & Cost Report.** Two endpoints:

1. `GET /v1/organizations/usage_report/messages` — token rollups.
2. `GET /v1/organizations/cost_report` — USD cost rollups.

Canonical references:

- <https://docs.anthropic.com/en/api/usage-cost-api>
- <https://platform.claude.com/docs/en/build-with-claude/usage-cost-api>
- <https://docs.anthropic.com/en/api/admin-api/usage-cost/get-messages-usage-report>

Key facts:

- **Auth**: `x-api-key: <ANTHROPIC_ADMIN_API_KEY>` (Admin keys, not regular
  workspace keys). Create at console.anthropic.com → Organization Settings →
  Admin Keys. Regular API keys return 403.
- **Headers**: `anthropic-version: 2023-06-01`.
- **Parameters**:
  - `starting_at` (ISO-8601 / Unix seconds)
  - `ending_at`
  - `bucket_width` — `"1d"` / `"1h"` / `"1m"` on usage; `"1d"` on cost
  - `group_by` — workspace_id, description, model, api_key_id,
    service_tier, context_window, inference_geo
  - `api_key_ids[]` — filter
  - `workspace_ids[]` — filter
  - `limit` / `page` — pagination
- **Data freshness**: ≤ 5 minutes for API traffic.
- **Rate limits**: designed for 1 req/min sustained; burst allowed for
  paginated downloads.

### Secondary / Fallback

- **Console UI export** — `console.anthropic.com` → Usage → download CSV.
  Useful as a sanity check but not programmatic.
  Source: <https://support.anthropic.com/en/articles/9534590-cost-and-usage-reporting-in-console>.
- **Per-request `message.usage` on live traffic** — when Costly proxies or
  sidecars Messages API traffic (not applicable today, but Helicone / Portkey
  / LiteLLM Proxy do it), every response includes `input_tokens`,
  `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`,
  `cache_creation.ephemeral_5m_input_tokens`,
  `cache_creation.ephemeral_1h_input_tokens`, `service_tier`.
- **Bedrock / Vertex hosted Claude** — billed via AWS CUR / GCP BigQuery
  billing export, not through Anthropic. Separate connector path.

### Gotchas

- **Admin key vs regular key** — the single most common failure mode. Our
  current connector's `test_connection()` calls `/v1/models` which works
  with any key, then `fetch_costs()` calls `/v1/organizations/usage` which
  403s on non-admin keys. Users see "connection successful" and then empty
  cost data.
- **Endpoint path drift** — `/v1/organizations/usage` (used in our code) is
  not the current documented path. The documented path is
  `/v1/organizations/usage_report/messages`. Anthropic likely keeps legacy
  aliases live, but we should migrate.
- **`group_by` now supports more dimensions** than we request (we only pass
  `model`). Missing: `workspace_id`, `api_key_id`, `service_tier`,
  `context_window`, `inference_geo`.
- **`service_tier` matters for pricing** — the Usage API returns tokens
  aggregated _without_ tier weighting. To reconstruct real USD cost from
  the tokens endpoint, callers must group by tier and apply tier-specific
  multipliers. Cleaner: use `/cost_report` directly, which already returns
  dollars.
- **Cache tokens vs billed tokens** — usage API returns `input_tokens`,
  `output_tokens`, `cache_read_input_tokens`,
  `cache_creation_input_tokens` separately. Naïvely summing them inflates
  counts; cost math must apply the 0.10× / 1.25× / 2.0× multipliers.
- **Batch vs standard** — if a workload is partly batch, the Usage endpoint
  emits two rows (same model, different tier). Collapsing them without
  tier-aware pricing gives the wrong cost.
- **Claude Code subscription traffic is NOT visible** — Claude Max/Pro users
  don't bill per token. See `claude-code.md`.
- **`inference_geo`** — new dimension for data residency verification.
  Enterprise FinOps users care about this.
- **Deprecations** — Claude 3.x family (3, 3.5, 3.7) is deprecated. Anthropic
  publishes deprecation notices on
  <https://docs.anthropic.com/en/docs/resources/model-deprecations>.

## Schema / Fields Available

From `/v1/organizations/usage_report/messages`:

| Field | Type | Semantic |
|---|---|---|
| `starting_at` | ISO-8601 | Bucket start |
| `ending_at` | ISO-8601 | Bucket end |
| `workspace_id` | str | Workspace id (if grouped) |
| `api_key_id` | str | Key id (if grouped) |
| `model` | str | Full model string |
| `service_tier` | enum | `"standard"` / `"priority"` / `"batch"` |
| `context_window` | enum | `"0-200k"` / `"200k-1m"` (when applicable) |
| `inference_geo` | str | Routing region |
| `input_tokens` | int | Non-cached input |
| `output_tokens` | int | Generated output |
| `cache_read_input_tokens` | int | Cache reads (0.10×) |
| `cache_creation_input_tokens` | int | Total cache writes |
| `server_tool_use.web_search_requests` | int | Billed web search calls |

From `/v1/organizations/cost_report`:

| Field | Type | Semantic |
|---|---|---|
| `starting_at` / `ending_at` | ISO-8601 | Bucket |
| `workspace_id` | str | Workspace (if grouped) |
| `description` | str | Line-item description (e.g. `"claude-opus-4-6-cache-write-5m"`) |
| `amount.value` | decimal | USD cost |
| `amount.currency` | enum | `"USD"` |

## Grouping Dimensions

Supported `group_by` values on Usage + Cost reports (confirm per endpoint —
set differs slightly):

- `workspace_id` — per-workspace chargeback.
- `api_key_id` — per-app / per-service attribution (each app gets its own key).
- `model` — default dimension for cost optimisation.
- `service_tier` — required if you want honest cost-from-tokens math.
- `context_window` — to spot "we're running on 1M when 200k would suffice".
- `inference_geo` — compliance.
- `description` (cost report only) — finest-grain line items.

## Open-Source Tools Tracking This Platform

| Tool | URL | Approx stars | License | What it tracks | Source |
|---|---|---|---|---|---|
| **LiteLLM** | <https://github.com/BerriAI/litellm> | 19k+ | MIT | Proxy / SDK; emits per-request `response_cost` and writes to S3/Postgres/Prometheus sinks | Wrapping SDK |
| **LiteLLM pricing JSON** | <https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json> | (same repo) | MIT | Centralised per-model price table for every Claude SKU, including cache tiers | Manual PRs from community (lag Anthropic by ≤48h) |
| **Helicone** | <https://github.com/Helicone/helicone> | ~3k | Apache-2.0 | Proxy with cost dashboard, prompt management, caching, evals | Wrapping proxy (`oai.helicone.ai`) |
| **Langfuse** | <https://github.com/langfuse/langfuse> | ~7k | MIT (+ commercial cloud) | LLM trace + cost tracking, evals, datasets, prompt mgmt; acquired by ClickHouse 2024 | SDK / OpenTelemetry |
| **Phoenix (Arize)** | <https://github.com/Arize-ai/phoenix> | ~4k | Elastic License 2.0 | OpenInference tracing + eval, cost surfaced on spans | OpenInference SDK |
| **OpenLLMetry / Traceloop** | <https://github.com/traceloop/openllmetry> | ~2.5k | Apache-2.0 | OpenTelemetry SDK for LLM spans; cost derived from model catalog | OTEL |
| **Portkey** | <https://github.com/Portkey-AI/gateway> | ~5k | MIT | AI gateway with cost tracking, routing, guardrails | Gateway |
| **PostHog LLM analytics** | <https://github.com/PostHog/posthog> | ~20k | MIT | Product-analytics side has LLM cost cards | SDK |
| **OpenPipe** | <https://github.com/OpenPipe/OpenPipe> | ~2.5k | Apache-2.0 | Fine-tune-first; tracks cost and savings estimates | Proxy |
| **Anthropic Usage CLI** (unofficial, various) | search `anthropic-usage-cli` on GitHub | <100 each | MIT | Thin wrappers over Admin API usage endpoint | Direct API |
| **honeycomb/refinery Anthropic integration** | <https://docs.honeycomb.io/integrations/anthropic-usage-monitoring> | N/A | Commercial | Official Honeycomb integration for Anthropic Usage & Costs | Admin API |
| **ccusage** | <https://github.com/ryoppippi/ccusage> | ~5k | MIT | Technically Claude Code; relevant because many Anthropic users now have Claude Code traffic they can attribute via JSONL | Local JSONL |
| **LangSmith** (LangChain) | <https://github.com/langchain-ai/langsmith-sdk> | (in org) | MIT | Tracing + cost; natively supports Anthropic | SDK |

None of these directly replace an Admin API puller; they wrap or sidecar live
traffic. For the "I need my invoice" use case, the Admin API is the only
source of truth.

## How Competitors Handle This Platform

- **Vantage (vantage.sh)** — Adds Anthropic as an AI provider alongside
  OpenAI/Gemini in its "AI spend intelligence" product. Breaks down by
  model, workspace, team. Pulls via Admin API. Source:
  <https://www.vantage.sh/blog/top-platforms-for-managing-ai-costs>.
  Standalone product: <https://vantageaiops.com>.
- **CloudZero (cloudzero.com)** — First cloud-cost platform to integrate
  with Anthropic directly (announced 2025). Pulls Admin API data and
  normalises alongside AWS/Azure/GCP. Notable: cost allocation by customer,
  region, app, user tier; cost-per-token + cost-per-user derived metrics;
  natural-language query via MCP server ("compare OpenAI and Anthropic for
  last month"). Source:
  <https://www.cloudzero.com/blog/cloudzero-anthropic/>.
- **Finout (finout.io)** — MegaBill ingests Anthropic invoices; Admin API
  now supplements for token-level. Anthropic-specific pricing calculator
  published. Source:
  <https://www.finout.io/blog/anthropic-vs-openai-billig-api>.
- **Datadog CCM** — Anthropic usage & costs integration launched 2025;
  pulls Admin API into Cloud Cost Management dashboards alongside LLM
  Observability traces. Docs:
  <https://docs.datadoghq.com/integrations/anthropic-usage-and-costs/>.
  Blog: <https://www.datadoghq.com/blog/anthropic-usage-and-costs/>.
- **Revefi (revefi.com)** — Warehouse-focused, recent "track every token"
  messaging but no first-class Anthropic connector documented.
- **Honeycomb** — Official Anthropic Usage & Cost monitoring integration
  (Admin API ingester that emits OTEL metrics). Source:
  <https://docs.honeycomb.io/integrations/anthropic-usage-monitoring>.
- **Select.dev, Keebo, Espresso AI, Chaos Genius/Flexera** — Warehouse-only.
  Not applicable.
- **Amberflo** — Billing/metering platform. Recently added AI tooling but
  still enterprise-billing-first.
- **Cloudchipr** — Generic cloud cost; no Anthropic-specific dashboard.

The commercial frontier is (a) joint cloud+AI unification (CloudZero, Datadog,
Vantage) and (b) per-feature / per-customer cost attribution. Costly should
match the Admin API depth _and_ tie it to the rest of the data-platform cost
line.

## Books / Published Material / FinOps Literature

- **Cloud FinOps** (Storment & Fuller, O'Reilly, 2nd ed, 3rd in progress) —
  <https://www.oreilly.com/library/view/cloud-finops-2nd/9781492098348/>.
  The canonical FinOps book; the framework applies directly to LLM spend.
- **FinOps Foundation — FinOps for AI Overview** —
  <https://www.finops.org/wg/finops-for-ai-overview/>. Working-group
  whitepaper (2025). The closest thing to a recognised AI FinOps standard.
- **FinOps Foundation — AI Cost Estimation** and **How to Forecast AI** —
  sibling working-group papers.
- **FinOps Foundation — Model Context Protocol (MCP): An AI for FinOps
  Use Case** — <https://www.finops.org/wg/model-context-protocol-mcp-ai-for-finops-use-case/>.
- **CloudZero — FinOps for Claude** —
  <https://www.cloudzero.com/blog/finops-for-claude/>. Vendor-slanted but
  the most detailed practitioner text on managing Claude spend.
- **Finout — Anthropic API Pricing in 2026: Complete Guide** —
  <https://www.finout.io/blog/anthropic-api-pricing>.
- **Finout — Anthropic vs OpenAI Billing API: What FinOps Teams Need to Know** —
  <https://www.finout.io/blog/anthropic-vs-openai-billig-api>.
- **Vantage — Anthropic vs OpenAI API costs** —
  <https://www.vantage.sh/blog/anthropic-vs-openai-api-costs>.
- **Morph — Anthropic API Pricing: The Real Cost of Claude for Coding Agents** —
  <https://www.morphllm.com/anthropic-api-pricing>.
- **MetaCTO — Claude API Pricing 2026: Full Anthropic Cost Breakdown** —
  <https://www.metacto.com/blogs/anthropic-api-pricing-a-full-breakdown-of-costs-and-integration>.
- **Evolink — Claude API Pricing 2026** —
  <https://evolink.ai/blog/claude-api-pricing-guide-2026>. One of the few
  write-ups to call out Opus 4.7's tokenizer uplift.
- **IntuitionLabs — Claude Pricing Explained** —
  <https://intuitionlabs.ai/articles/claude-pricing-plans-api-costs>.
- **Silicon Data — Claude API Pricing 2026** —
  <https://www.silicondata.com/use-cases/anthropic-claude-api-pricing-2026/>.
- **Anthropic Trust Center** — <https://trust.anthropic.com>. Relevant for
  enterprise-pitch compliance claims (SOC2 Type II, HIPAA BAA, GDPR DPA).
- **Datadog Blog — "Monitor Claude usage and cost data with Datadog CCM"** —
  <https://www.datadoghq.com/blog/anthropic-usage-and-costs/>.

There is **no printed book specific to Anthropic cost management**; the
FinOps Foundation working group is the closest thing to a recognised
standard, and Finout / CloudZero / MetaCTO blogs are the most actionable
practitioner material.

## Vendor Documentation Crawl

- **Pricing page** — <https://platform.claude.com/docs/en/about-claude/pricing>.
  Per-model list price, cache multipliers, batch discount.
- **Prompt caching** —
  <https://platform.claude.com/docs/en/build-with-claude/prompt-caching>.
  The 0.10× / 1.25× / 2.0× constants live here. Also covers cache
  invalidation rules (model change invalidates; system-prompt edit
  invalidates; inserting before a cached breakpoint invalidates).
- **Service tiers** — <https://docs.anthropic.com/en/api/service-tiers>.
  standard / priority / batch; `service_tier` request parameter.
- **Batch API** — <https://docs.anthropic.com/en/api/batches>. How to submit,
  poll, retrieve; 50% discount stacks with cache.
- **Managed Agents** (new, 2025) — meter structure, priority premium.
- **Admin API overview** —
  <https://platform.claude.com/docs/en/build-with-claude/administration-api>.
- **Usage & Cost API reference** —
  <https://docs.anthropic.com/en/api/usage-cost-api> and
  <https://platform.claude.com/docs/en/build-with-claude/usage-cost-api>.
- **Get Messages Usage Report** (per-endpoint) —
  <https://docs.anthropic.com/en/api/admin-api/usage-cost/get-messages-usage-report>.
- **Cost report** — under the Admin API section; shape already summarised
  above.
- **Messages API reference** —
  <https://docs.anthropic.com/en/api/messages>. The `usage` subobject on
  responses is the authoritative per-request cost signal.
- **Model deprecations** —
  <https://docs.anthropic.com/en/docs/resources/model-deprecations>.
- **Release notes / changelogs** — Anthropic maintains per-product
  changelogs under `platform.claude.com/docs/*/whatsnew` (model cards carry
  explicit release dates; Opus 4.7 released 2026-04-16; Opus 4.6 released
  March 2026; Haiku 4.5 released winter 2025/26).
- **Regions / data residency** — `inference_geo` dimension covers US, EU,
  Japan routing. Enterprise plan grants explicit geographic pinning.
- **SLA / compliance** — <https://trust.anthropic.com>. Enterprise SLA, SOC2
  Type II, HIPAA BAA, GDPR DPA, data-retention controls. Relevant for
  enterprise pitch.
- **Support center — Cost and Usage Reporting in Console** —
  <https://support.anthropic.com/en/articles/9534590-cost-and-usage-reporting-in-console>.

## Best Practices (synthesized)

1. **Use `/cost_report` not `/usage_report/messages` as the cost source of
   truth.** Dollars are authoritative. Use the tokens endpoint only when the
   user needs per-token analytics that dollars don't expose.
2. **Always include `service_tier` in `group_by`.** Same `(model, day)` can
   span three tiers and each tier has different unit economics.
3. **Always separate cache_read / cache_write tokens from input tokens.**
   Cache reads are 10% of list; cache writes are 125% or 200%. A cache-heavy
   app priced with a flat "input × $3/M" model is 2–10× wrong.
4. **Admin key is required**. Detect non-admin keys in `test_connection` and
   surface a targeted error ("this key does not have `usage:read` scope;
   rotate to an Admin key from console.anthropic.com").
5. **Group by `workspace_id` and `api_key_id`** for chargeback. Anthropic's
   workspace abstraction is explicitly designed for this.
6. **Refresh pricing daily from LiteLLM** model_prices_and_context_window.json
   with a hard-coded fallback. Hand-maintained tables drift.
7. **Flag Opus 4.7 tokenizer uplift** when we see 4.7 traffic overlapping
   with 4.6 history — effective cost rises even at identical rates.
8. **Reconcile against invoice monthly.** Anthropic's Usage data is ≤5 min
   fresh but Stripe invoices are end-of-cycle; reconciling catches billing
   adjustments, disputed charges, and spare discounts.
9. **Surface Batch-vs-Standard split.** "You could save 50% by switching
   this non-latency-critical workload to Batch" is actionable.
10. **Separate Vertex/Bedrock-hosted Claude** — those are NOT visible on
    Anthropic Admin API. Detect by model-name prefix + platform and hand
    off to the right connector.

## Costly's Current Connector Status

**File:** `backend/app/services/connectors/anthropic_connector.py`

The connector is ~137 lines. What it does:

- Accepts `credentials["api_key"]` (expected to be an Admin key).
- `test_connection()` hits `GET /v1/models` (works with any key — false
  positive risk).
- `fetch_costs(days)` hits `GET /v1/organizations/usage` with
  `granularity=daily`, `group_by=model`.
- Parses each entry into a `UnifiedCost` with `category=ai_inference`,
  `platform="anthropic"`, `resource=<model>`, `usage_quantity=total tokens`,
  and metadata `{input_tokens, output_tokens, model}`.
- Computes cost with a built-in `MODEL_PRICING` table: `claude-opus-4`,
  `claude-sonnet-4`, `claude-haiku-3-5`, `claude-sonnet-3-5`. Longest-prefix
  match; fallback to Sonnet pricing.

What's broken:

- **Endpoint path is stale.** Documented endpoints are
  `/v1/organizations/usage_report/messages` +
  `/v1/organizations/cost_report`. The connector calls `/v1/organizations/usage`.
  Either Anthropic keeps a legacy alias (works today, may break) or the call
  already returns empty/404 on most tenants.
- **Parameters are stale.** Documented params are `starting_at` / `ending_at`
  (ISO-8601). The connector passes `start_date` / `end_date` strings with
  `granularity=daily`. The current spec uses `bucket_width` (`"1d"`).
- **No cache tokens in the math.** `cache_read_input_tokens` and
  `cache_creation_input_tokens` are not pulled. Cache-heavy apps are
  mis-priced.
- **No `service_tier` dimension.** Batch and Priority traffic are lumped
  with Standard, mispricing by 50%+ each way.
- **No workspace / api-key breakdown.**
- **Silently returns `[]` on failure** — the `fetch_costs` path catches
  everything with `except Exception: pass`, swallowing 401/403/404 errors.
  Users see a connection marked "successful" but zero cost data.
- **Pricing table is incomplete.** Missing Opus 4.6 and 4.7, Sonnet 4.5 and
  4.6, Haiku 4.5, Haiku 4, Haiku 3 — all resolve to Sonnet-4 fallback which
  under-prices Opus by 5× and over-prices Haiku by 3×.
- **Opus 4.7 tokenizer uplift is not acknowledged.**
- **Bedrock/Vertex-hosted Claude is not excluded.** If a customer uses
  both raw Anthropic and Bedrock Claude and has an Admin key for both, the
  usage counts would double (the Admin API shows only direct Anthropic
  traffic, so this is not actually an issue today; but user configuration
  should flag the intent explicitly).

## Gaps Relative to Best Practice

1. **Endpoint migration** to `/v1/organizations/usage_report/messages` + `/v1/organizations/cost_report` with modern params (`starting_at`, `ending_at`, `bucket_width`).
2. **Use the `cost_report` endpoint as primary** and `usage_report/messages` as secondary (for token analytics).
3. **Add cache + service-tier dimensions** to metadata so the UI can pivot.
4. **Workspace + api-key grouping** — single biggest enterprise unlock.
5. **`inference_geo` metadata** — compliance pitch differentiator.
6. **Pricing table refresh** from LiteLLM model_prices_and_context_window.json.
7. **Complete pricing table** — Opus 4.7, Opus 4.6, Sonnet 4.7, Sonnet 4.6, Sonnet 4.5, Haiku 4.5, Haiku 4, Haiku 3.
8. **Error handling** — surface 401 / 403 (non-admin key) / 404 distinctly. Stop returning `[]` on exception.
9. **Opus 4.7 tokenizer-uplift banner** when 4.7 share crosses a threshold.
10. **Batch-vs-standard savings hint** for non-latency-critical workloads.
11. **Admin key detection** in `test_connection()` — probe
    `/v1/organizations/usage_report/messages?limit=1` instead of `/v1/models`.
12. **Unified with Claude Code** — same org may have both Admin-API-visible
    traffic and Claude Code subscription traffic. Surface both sources in
    one Anthropic page.

## Roadmap

**Near-term (ship this week):**

- Migrate to `/cost_report` as primary; fall back to `/usage_report/messages`.
- Expand `MODEL_PRICING` table (Opus 4.7/4.6, Sonnet 4.7/4.6/4.5, Haiku 4.5/4/3).
- Replace `except Exception: pass` with structured error surfacing.
- Admin-key probe in `test_connection()`.
- Add cache_read / cache_write_5m / cache_write_1h in metadata.

**Medium (next month):**

- `workspace_id` + `api_key_id` grouping + per-workspace drill-down page.
- Nightly pricing sync from LiteLLM JSON.
- `service_tier` split + "switch to Batch" recommendation.
- `inference_geo` column.
- Monthly invoice reconciliation view.
- Opus 4.7 tokenizer-uplift banner.

**Long (quarter):**

- Unify Anthropic + Claude Code into a single platform view.
- Cross-platform AI cost page (Anthropic + OpenAI + Gemini).
- Anomaly alerts: "your cache-hit ratio dropped from 72% → 31%; prompt
  changed on Mar 4?"
- Bedrock/Vertex Claude reconciliation (claim the Anthropic share of those
  bills from the cloud connectors).
- Managed Agents cost breakdown.

## Change Log

- 2026-04-24: Initial knowledge-base created by overnight research run.
- 2026-04-24 (lane/anthropic): Per-workspace anomaly surfaces + priority-tier
  isolation shipped. Connector now emits synthetic per-workspace daily
  rollup UnifiedCost records (`resource="workspace:<id>"`,
  `metadata.type="rollup"`, `metadata.rollup_type="workspace"`) that the
  generic `anomaly_detector` per-resource z-score path picks up as its own
  resource series — so a spike in any one workspace now lights up on
  `/api/anomalies` without any Anthropic-specific code in that path.
  Priority tier expanded from flat `priority` (1.25×) to three isolated
  tiers: `priority` (1.25×), `priority_on_demand` (1.5×), and `flex` (0.5×).
  Every non-standard tier gets its own UnifiedCost record and is tagged
  `metadata.isolated_tier=true` for budget tracking. Deprecated Claude 3.x
  models surface a human-readable `metadata.deprecation_notice` pointing
  at the 4.x migration target, and per-workspace rollups track
  `deprecated_cost_usd` so the dashboard can quantify migration debt.
  `inference_geo` is now first-class — promoted to `UnifiedCost.project`
  so data-residency dashboards can group on it. Opt-in per-api_key rollups
  (`emit_api_key_rollups=True`) for orgs that want per-service attribution.
  `/api/ai-costs` extended (read-only) with `workspace_breakdown`,
  `tier_breakdown`, and `kpis.deprecated_spend_usd`; `metadata.type=rollup`
  is excluded from primary aggregates to avoid double-counting.
  Grade: **A-**. Gap remaining: OpenTelemetry trace ingestion path (tracked
  on the lane backlog).

## Re-recording contract fixtures

Contract tests for this connector live at `backend/tests/contract/test_anthropic.py`
and load JSON fixtures from `backend/tests/fixtures/anthropic/`. The fixtures are
intentionally hand-written from the public API docs so they don't leak any
real account data — every contributor can run the suite offline.

To capture fresh fixtures against a real Anthropic Admin account when the API
schema drifts, set credentials and run pytest with `--record-mode=once`:

```bash
cd backend
ANTHROPIC_ADMIN_KEY=sk-ant-admin... \
    pytest tests/contract/test_anthropic.py --record-mode=once
```

Then sanitize the captured JSON (strip account ids, emails, tokens) before
committing. See `docs/testing/contract-tests.md` for the philosophy.


