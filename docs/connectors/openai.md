# OpenAI — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

OpenAI is the largest foundation-model vendor, offering GPT-4.1, GPT-5.x,
o-series reasoning models, embeddings, vision, TTS, Whisper, image gen
(DALL-E 3, gpt-image-1), and the Assistants/Responses API. Costly's
`openai_connector.py` pulls daily token rollups from `/v1/organization/usage/*`
and falls back to `/v1/organization/costs`, estimating cost with a built-in
per-million price table. Current grade: **B-** — the connector uses the right
endpoints and already has a fallback path, but it's missing cached-input
pricing, batch / flex / priority tier awareness, audio + image per-unit
pricing, project/user grouping, and has pricing-table rot on the reasoning
models. This doc is the fix list.

## Pricing Model (from vendor)

Canonical sources:

- <https://openai.com/api/pricing/>
- <https://developers.openai.com/api/docs/pricing>
- <https://platform.openai.com/docs/pricing>

All prices USD per million tokens, standard tier, list / non-batch, non-cached.

### Chat / reasoning models (2026-04)

| Model | Input | Cached input | Output | Context |
|---|---|---|---|---|
| GPT-5.4 (flagship) | varies | 90% off | varies | 1M+ |
| GPT-5.1 | varies | 90% off | varies | 1M |
| GPT-5 / GPT-5 mini / GPT-5 nano | per nicolalazzari breakdown | 90% off | — | — |
| GPT-4.1 | $2.00 | $0.50 (75% off) | $8.00 | 1M |
| GPT-4.1 mini | $0.40 | $0.10 | $1.60 | 1M |
| GPT-4.1 nano | $0.10 | $0.025 | $0.40 | 1M |
| GPT-4o | $2.50 | $1.25 (50% off) | $10.00 | 128k |
| GPT-4o mini | $0.15 | $0.075 | $0.60 | 128k |
| GPT-4 turbo | $10.00 | — | $30.00 | 128k |
| GPT-4 | $30.00 | — | $60.00 | 8k / 32k |
| GPT-3.5 turbo | $0.50 | — | $1.50 | 16k |
| o1 (deprecated Jan 2026) | $15.00 | $7.50 | $60.00 | 200k |
| o1-pro | $150.00 | — | $600.00 | 200k |
| o1-mini | $1.10 | — | $4.40 | 128k |
| o3 | $2.00 | $0.50 | $8.00 | 200k |
| o3-mini | $1.10 | — | $4.40 | 200k |
| o4-mini | $1.10 | — | $4.40 | 200k |

There is NO `o4` model as of 2026-04 — only `o4-mini`. The `o3` name replaced
the expensive `o1` flagship reasoning model; o3 ships at $2.00 / $8.00 (an
87% cut vs o1). Source:
<https://www.aipricing.guru/openai-pricing/>,
<https://nicolalazzari.ai/articles/openai-api-pricing-explained-2026>.

### Embeddings

| Model | Price |
|---|---|
| text-embedding-3-large | $0.13 / M input |
| text-embedding-3-small | $0.02 / M input |
| text-embedding-ada-002 (legacy) | $0.10 / M input |

### Audio / image / vision

- **Whisper** (`whisper-1`): $0.006 per minute of audio input.
- **TTS** (`tts-1`): $15 per 1M characters input (HD: $30 / 1M).
- **gpt-4o-audio-preview / gpt-4o-realtime-preview** — separate per-token
  rates for audio input and audio output (audio tokens are denser than text;
  see OpenAI pricing page for the tier).
- **DALL-E 3**: $0.040 per 1024×1024 image (standard), $0.080 (HD).
- **gpt-image-1** (new): per-image pricing by size and quality; priced
  differently from DALL-E 3.
- **Vision** (image input to GPT-4.1/4o): billed as extra tokens based on
  patch count — "auto"/"low" detail ≈ 85 tokens, "high" detail per 512×512
  tile.

### Pricing modifiers

- **Prompt caching** (discount when prompt prefix matches a recent call):
  - GPT-5 family: 90% off on cached input tokens.
  - GPT-4.1 family: 75% off.
  - GPT-4o / o-series: 50% off.
  Source:
  <https://nicolalazzari.ai/articles/openai-api-pricing-explained-2026>.
- **Batch API** — 50% discount on both input and output. 24-hour turnaround.
  Docs: <https://platform.openai.com/docs/guides/batch>.
- **Flex processing** — Batch rates plus prompt caching; slower than
  synchronous, may return "resource unavailable". Docs:
  <https://platform.openai.com/docs/guides/flex-processing>. Combined with
  caching, batch GPT-4.1 processes cached input at $0.25 per million tokens.
- **Priority Processing** — capacity-reserved tier for enterprise; higher
  unit cost. Exposed via service tier on the request.
- **Fine-tuning** — training cost (per 1M tokens of training data) plus
  inference surcharge on the fine-tuned model.
- **Region** — single global price in USD. Azure OpenAI is a separate
  billing line (under the Azure bill, not the OpenAI bill).

## Billing / Usage Data Sources

### Primary

**OpenAI Organization Usage / Cost API** —
<https://cookbook.openai.com/examples/completions_usage_api>,
<https://platform.openai.com/docs/api-reference/usage>.

- `GET /v1/organization/usage/completions` — chat/completions tokens.
- `GET /v1/organization/usage/embeddings` — embedding tokens.
- `GET /v1/organization/usage/images` — image-gen units.
- `GET /v1/organization/usage/audio` — audio units.
- `GET /v1/organization/usage/moderations`
- `GET /v1/organization/usage/vector_stores`
- `GET /v1/organization/usage/code_interpreter_sessions`
- `GET /v1/organization/costs` — single endpoint for USD spend by line item.

Auth: **Admin API key** from
<https://platform.openai.com/settings/organization/admin-keys>. Regular
project / user keys 403 on these endpoints.

Params: `start_time` (Unix seconds), `end_time`, `bucket_width` (`"1d"` is
the only supported value on costs today; usage supports `"1h"` /
`"1d"`), `group_by` (array — `model`, `project_id`, `user_id`, `api_key_id`,
`batch`, `service_tier`), `limit`, `page`.

### Secondary / Fallback

- **Per-request `response.usage` in the SDK** — every chat/completion
  response includes `prompt_tokens`, `completion_tokens`, `total_tokens`, and
  (since late 2024) `prompt_tokens_details.cached_tokens` +
  `completion_tokens_details.reasoning_tokens` for o-series. Wrap your SDK
  call with a logger and you have token-perfect attribution; what's
  missing is the global per-org view.
- **Console export** — <https://platform.openai.com/usage>. Download CSV by
  date range. Manual.
- **Azure OpenAI** — routes through Azure Cost Management, not OpenAI
  Organization API. Different connector path entirely; use the Azure /
  Microsoft Cost Management connector.

### Gotchas

- **Admin API key vs Project API key** — Project keys return 403 on
  `/v1/organization/*`. Our connector currently tests with `/v1/models`
  which succeeds on any key, then hits the org endpoint — surfacing the
  limitation as a note in `test_connection()` response.
- **`/v1/organization/costs` returns dollars but only with `bucket_width=1d`
  today** — you cannot get per-hour cost data.
- **Costs endpoint returns cents** — our connector divides by 100 already;
  cross-check the API version because the `amount.value` field currently
  returns dollars directly (`"value": 23.45`) per the 2025 API revision.
  Verify before changing.
- **Cached tokens aren't on the usage endpoint** — per the Jan 2025 API
  update the `/usage/completions` response includes `input_cached_tokens`
  but our connector ignores it. Result: cache-heavy apps are over-priced.
- **Batch vs real-time on the same model** are returned as the same row
  unless you `group_by=batch`. Cost math that assumes all tokens are
  real-time over-estimates the batch share by 50%.
- **Reasoning tokens (o-series)** — the `completion_tokens_details.reasoning_tokens`
  field counts tokens generated for chain-of-thought that are billed as
  output but invisible to the user. The usage API surfaces them as output
  tokens directly, so no adjustment needed — but users often ask "why is
  my output token count 10× what I see?" and the answer is reasoning tokens.
- **Image / audio / embedding pricing varies per unit type** — not a pure
  per-token model. Our connector's `MODEL_PRICING` table treats TTS as
  `$15/M input` which is the right _character_ rate but the usage API returns
  characters in `output_tokens` for TTS, and the connector treats it as
  tokens. Spot-check required.
- **Fine-tuned models** — appear as `ft:gpt-4o-mini:your-org::AbCdEf`. Our
  longest-prefix match hits `gpt-4o-mini` correctly but doesn't add the
  fine-tuned inference surcharge (currently $0.30/M input, $1.20/M output
  for 4o-mini fine-tuned).
- **Deprecations** — OpenAI rolls deprecations twice a year. `gpt-4-32k`,
  `text-davinci-003`, `code-davinci-002` already gone; o1 scheduled for
  removal Jan 2026.

## Schema / Fields Available

From `/v1/organization/usage/completions` (Jan 2025 shape):

| Field | Type | Semantic |
|---|---|---|
| `data[].start_time` | unix sec | Bucket start |
| `data[].end_time` | unix sec | Bucket end |
| `data[].results[].model` | str | Model name |
| `data[].results[].input_tokens` | int | Non-cached input |
| `data[].results[].input_cached_tokens` | int | Cache-hit input (discounted) |
| `data[].results[].output_tokens` | int | Completion tokens |
| `data[].results[].input_audio_tokens` | int | Audio input tokens (realtime / audio models) |
| `data[].results[].output_audio_tokens` | int | Audio output tokens |
| `data[].results[].num_model_requests` | int | Request count |
| `data[].results[].project_id` | str | Project (if grouped) |
| `data[].results[].user_id` | str | User (if grouped) |
| `data[].results[].api_key_id` | str | Key (if grouped) |
| `data[].results[].batch` | bool | Whether this row is batch-api traffic |

From `/v1/organization/costs`:

| Field | Type | Semantic |
|---|---|---|
| `data[].start_time`, `end_time` | unix sec | Bucket |
| `data[].results[].line_item` | str | e.g. `"gpt-4.1-input"`, `"gpt-4.1-cached-input"`, `"gpt-4.1-output"`, `"batch-gpt-4.1-input"` |
| `data[].results[].amount.value` | decimal | USD cost |
| `data[].results[].amount.currency` | enum | `"usd"` |
| `data[].results[].project_id` | str | If grouped |

## Grouping Dimensions

Supported `group_by` on usage endpoints:

- `model` — baseline dimension.
- `project_id` — OpenAI's workspace equivalent; key for chargeback.
- `user_id` — per-user attribution (works only if the client passes `user`
  on the request; otherwise returns `unknown`).
- `api_key_id` — per-key (e.g. separate keys per service).
- `batch` — split batch vs real-time.
- `service_tier` (on newer models) — standard / priority / flex.

On costs endpoint: `project_id`, `line_item` (default), `service_tier`.

## Open-Source Tools Tracking This Platform

| Tool | URL | Approx stars | License | What it tracks | Source |
|---|---|---|---|---|---|
| **LiteLLM** | <https://github.com/BerriAI/litellm> | 19k+ | MIT | Proxy/SDK; emits `response_cost`; writes to Prometheus/Postgres/S3/BigQuery/ClickHouse | SDK wrap |
| **LiteLLM pricing JSON** | <https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json> | (same repo) | MIT | Pricing table for every OpenAI SKU incl. cached + batch | Manual PRs |
| **Helicone** | <https://github.com/Helicone/helicone> | ~3k | Apache-2.0 | Proxy + cost dashboard, prompt mgmt, evals | Proxy (`oai.helicone.ai`) |
| **Langfuse** | <https://github.com/langfuse/langfuse> | ~7k | MIT (+commercial) | LLM trace + cost, evals, datasets; acquired by ClickHouse | SDK / OTEL |
| **Arize Phoenix + OpenInference** | <https://github.com/Arize-ai/phoenix>, <https://github.com/Arize-ai/openinference> | ~4k / ~800 | Elastic License 2.0 / Apache-2.0 | OTEL instrumentation for OpenAI SDK + Agents SDK, cost on spans | OpenInference SDK |
| **OpenLLMetry (Traceloop)** | <https://github.com/traceloop/openllmetry> | ~2.5k | Apache-2.0 | OTEL SDK for OpenAI calls; cost from catalog | OTEL |
| **Portkey Gateway** | <https://github.com/Portkey-AI/gateway> | ~5k | MIT | AI gateway; cost tracking; provider-routing | Gateway |
| **LangSmith** | <https://github.com/langchain-ai/langsmith-sdk> | (in org) | MIT | LangChain's tracing; cost on spans | SDK |
| **OpenPipe** | <https://github.com/OpenPipe/OpenPipe> | ~2.5k | Apache-2.0 | Fine-tune-first; cost + savings estimator | Proxy |
| **PostHog LLM analytics** | <https://github.com/PostHog/posthog> | ~20k | MIT | Product-analytics LLM cost cards | SDK |
| **OpenAI cookbook examples** | <https://cookbook.openai.com/examples/completions_usage_api> | (in org) | MIT | Reference impl of Usage + Costs API pagination | Admin API |
| **n8n OpenAI usage tracker workflow** | <https://n8n.io/workflows/6002-track-openai-admin-api-usage-and-costs-automatically-with-google-sheets/> | N/A | community | Pre-built n8n workflow: Admin API → Google Sheets | Admin API |
| **tokscale** | <https://github.com/junhoyeo/tokscale> | ~800 | MIT | Multi-agent incl. Codex CLI; relevant for OpenAI-via-Codex traffic | Per-tool storage |
| **TokenTracker** | <https://github.com/mm7894215/TokenTracker> | ~400 | MIT | Multi-agent dashboard incl. Codex | Local |
| **coding_agent_usage_tracker** | <https://github.com/Dicklesworthstone/coding_agent_usage_tracker> | ~200 | MIT | Unified quota view across Codex, Claude, Gemini, Cursor, Copilot | Per-tool |
| **ccusage** | <https://github.com/ryoppippi/ccusage> | ~5k | MIT | Also parses Codex CLI JSONLs since recent versions | Local |
| **agentsview** | <https://github.com/wesm/agentsview> | ~2k | MIT | Parses Codex CLI sessions | SQLite |

## How Competitors Handle This Platform

- **Vantage (vantage.sh)** — OpenAI + Anthropic + Gemini under the AI spend
  intelligence product. Breaks down by model, workspace, team; surfaces
  cheaper-model suggestions and prompt-caching hints. Source:
  <https://www.vantage.sh/blog/top-platforms-for-managing-ai-costs>.
- **CloudZero** — OpenAI integration via Admin API + LiteLLM. MCP server
  natural-language queries ("compare OpenAI and Anthropic costs per 1k
  tokens"). Unified with AWS/Azure/GCP. Source:
  <https://www.cloudzero.com/blog/cloudzero-litellm/>,
  <https://www.cloudzero.com/blog/openai-pricing/>.
- **Finout** — MegaBill ingests OpenAI invoice, Admin API supplements.
  Per-token + per-project attribution. Source:
  <https://www.finout.io/blog/track-openai-spend>.
- **Datadog CCM + LLM Observability** — launched "Monitor your OpenAI LLM
  spend with cost insights" 2025. OpenAI cost in CCM dashboards + token
  usage traces in LLM Observability. Source:
  <https://www.datadoghq.com/blog/monitor-openai-cost-datadog-cloud-cost-management-llm-observability/>.
- **Revefi** — Generic LLM cost messaging; no first-class OpenAI connector
  documented as of 2026-04.
- **Select.dev, Keebo, Espresso AI, Chaos Genius/Flexera** — Warehouse-only.
  N/A.
- **Amberflo** — Metering/billing platform. AI pricing modeling; does not
  provide the connector.
- **Cloudchipr** — Generic cloud cost; no OpenAI dashboard.
- **Honeycomb** — OTEL-based LLM observability; natively supports OpenAI
  SDK via OpenInference.
- **n8n / Zapier / Make** — low-code automation platforms with templates for
  pulling Admin API data into sheets/Slack/etc. (not FinOps, but widely used).

## Books / Published Material / FinOps Literature

- **Cloud FinOps** (Storment & Fuller, O'Reilly, 2nd ed) —
  <https://www.oreilly.com/library/view/cloud-finops-2nd/9781492098348/>.
- **FinOps Foundation — FinOps for AI Overview** —
  <https://www.finops.org/wg/finops-for-ai-overview/>.
- **FinOps Foundation — AI Cost Estimation / How to Forecast AI** — sibling
  working-group papers.
- **Finout — Bringing FinOps to Your LLMs: Understanding and Tracking OpenAI
  Spend** — <https://www.finout.io/blog/track-openai-spend>.
- **Finout — OpenAI API Pricing Calculator** —
  <https://www.finout.io/tools/openai-pricing>.
- **CloudZero — OpenAI API Cost In 2026: Every Model Compared** —
  <https://www.cloudzero.com/blog/openai-pricing/>.
- **Datadog Blog — Monitor your OpenAI LLM spend with cost insights** —
  <https://www.datadoghq.com/blog/monitor-openai-cost-datadog-cloud-cost-management-llm-observability/>.
- **OpenAI Cookbook — How to use the Usage API and Cost API to monitor your
  OpenAI usage** —
  <https://cookbook.openai.com/examples/completions_usage_api>. Reference
  implementation by OpenAI DevRel.
- **OpenAI Devs announcement** —
  <https://community.openai.com/t/introducing-the-usage-api-track-api-usage-and-costs-programmatically/1043058>.
- **Vantage — Anthropic vs OpenAI API Costs** —
  <https://www.vantage.sh/blog/anthropic-vs-openai-api-costs>.
- **eesel — The OpenAI Batch API: What it is and when to use it (2026)** —
  <https://www.eesel.ai/blog/openai-batch-api>.
- **Nicola Lazzari — OpenAI API Pricing 2026** —
  <https://nicolalazzari.ai/articles/openai-api-pricing-explained-2026>.
- **AI Pricing Guru — OpenAI API Pricing 2026: GPT-5.4, o3, o4-mini** —
  <https://www.aipricing.guru/openai-pricing/>.
- **MetaCTO — OpenAI API Pricing 2026: True Cost Guide** —
  <https://www.metacto.com/blogs/unlocking-the-true-cost-of-openai-api-a-deep-dive-into-usage-integration-and-maintenance>.
- **PE Collective — OpenAI API Pricing 2026** —
  <https://pecollective.com/tools/openai-api-pricing/>.
- **Curlscape — OpenAI API Pricing Guide 2026** —
  <https://curlscape.com/blog/openai-api-pricing-guide-2026>.
- **APICents — OpenAI API Pricing 2026: All Models & Costs** —
  <https://apicents.com/provider/openai>.

No printed book specifically on OpenAI cost management. The OpenAI Cookbook's
Usage/Cost API examples + FinOps Foundation AI working group are the
practitioner standard; vendor blogs (Finout, CloudZero, Datadog, Vantage)
fill the gap.

## Vendor Documentation Crawl

- **Pricing page (marketing)** — <https://openai.com/api/pricing/>.
- **Pricing page (developer)** — <https://developers.openai.com/api/docs/pricing>,
  <https://platform.openai.com/docs/pricing>. Machine-readable table; kept
  in sync with marketing page.
- **Usage API reference** —
  <https://platform.openai.com/docs/api-reference/usage>.
- **Costs API reference** — same section.
- **OpenAI Cookbook — Usage + Cost API walkthrough** —
  <https://cookbook.openai.com/examples/completions_usage_api>. The best
  reference implementation.
- **Batch API guide** — <https://platform.openai.com/docs/guides/batch>.
- **Flex processing** — <https://platform.openai.com/docs/guides/flex-processing>.
- **Prompt caching** — <https://platform.openai.com/docs/guides/prompt-caching>.
  Cache auto-engages for prompts ≥1024 tokens; TTL is 5–10 min typical but
  not contractually guaranteed.
- **Admin API keys** —
  <https://platform.openai.com/settings/organization/admin-keys>.
- **Usage Dashboard (legacy)** —
  <https://help.openai.com/en/articles/8554956-usage-dashboard-legacy>.
- **Release notes** — <https://platform.openai.com/docs/changelog>. Model
  additions and deprecations are announced here.
- **Region / data residency** — <https://platform.openai.com/docs/guides/data-residency>.
  EU Data Zone available since 2024; EU traffic stays in-region when enabled.
- **SLA / compliance** — OpenAI Enterprise ships with SOC 2 Type II, ISO
  27001, GDPR DPA, and — on request — HIPAA BAA.
- **Model deprecations** — <https://platform.openai.com/docs/deprecations>.
  Current notable: o1 scheduled Jan 2026; gpt-4-32k gone; older `text-davinci`
  gone; `gpt-3.5-turbo-0301` gone.
- **Responses API** (replaces Assistants API long-term) —
  <https://platform.openai.com/docs/guides/responses>. Own billing model
  where server-side tool calls and file uploads add line items beyond
  tokens.
- **Realtime API** — <https://platform.openai.com/docs/guides/realtime>.
  Audio input + audio output per-token pricing (denser than text).

## Best Practices (synthesized)

1. **Use the Costs API as the dollar-ground-truth** and Usage API for token
   analytics. Don't recompute cost from tokens if you can fetch dollars.
2. **Separate cached_input from input** when computing cost — 50% / 75% / 90%
   discount tiers are model-family-dependent and collapsing them
   over-prices cache-heavy workloads.
3. **Group by `batch`** to split real-time and batch spend. "$X could have
   been Batch" is an actionable recommendation.
4. **Group by `project_id`** for chargeback. OpenAI's project abstraction
   is their workspace analogue.
5. **Group by `user_id`** — but only when the SDK is passing `user` on each
   request. Otherwise rows get lumped under `null`.
6. **Refresh the pricing table from LiteLLM JSON nightly.** Hand-coded
   tables drift within weeks.
7. **Support Flex and Priority tiers** — new enterprise customers will have
   these rows on their usage feed.
8. **Fine-tuned model detection** — `ft:gpt-4o-mini:org:name:abc` must add
   the fine-tune surcharge.
9. **Image / audio / embedding** — do not shoehorn into per-token math.
   Add a classification that routes TTS/Whisper/DALL-E/image/embedding to
   the right per-unit pricing rule.
10. **Reasoning-token share** — when using o1/o3/o4-mini, surface
    `reasoning_tokens / output_tokens` so users understand why "short
    answer" queries run up big bills.
11. **Reconcile against monthly invoice** — Stripe invoice is ground truth.
    Costs API ≈ invoice but discounts/credits appear only on the invoice.
12. **Azure OpenAI is a separate world** — different billing pipeline
    (Azure Cost Management), different quotas. Detect and hand off.

## Costly's Current Connector Status

**File:** `backend/app/services/connectors/openai_connector.py`

~249 lines. What it does:

- Accepts `credentials["api_key"]` and optional `credentials["org_id"]`.
- `test_connection()` hits `/v1/models` then probes
  `/v1/organization/usage/completions?start_time=…` with `bucket_width=1d`
  to detect admin access; surfaces a "note: usage data requires Admin API
  key" message on 403.
- `fetch_costs(days)` primary path iterates `completions` + `embeddings`
  usage endpoints with `group_by=[model]`, `bucket_width=1d`.
- Fallback path: `/v1/organization/costs` with `group_by=[model]`.
- Pricing table `MODEL_PRICING` covers gpt-4.1 family, gpt-4o family,
  gpt-4-turbo, gpt-4, gpt-3.5-turbo, o1 family, o3 family, o4-mini, dall-e-3
  (zeroed — not token-priced), tts-1, whisper-1, text-embedding-3-small/large.
- Cost API response divided by 100 (assuming cents) — this may be wrong;
  Jan 2025 shape returns dollars.
- Emits `UnifiedCost` with `platform=openai`, `service=openai`,
  `resource=<model>`, `category=ai_inference`, metadata
  `{input_tokens, output_tokens, model, type?}`.

What's working:

- Right endpoints (`/v1/organization/usage/{completions,embeddings}` + `/v1/organization/costs`).
- Fallback logic from usage → cost.
- Admin-key detection in `test_connection()` (better than Anthropic).
- Longest-prefix match on pricing.

What's broken or missing:

- **No cached_input pricing** — the usage API returns `input_cached_tokens`
  and the connector throws it away. 50–90% cost inflation on cache-heavy
  apps.
- **No batch dimension** — all batch traffic is priced as standard,
  over-estimating by 2×.
- **No project_id / user_id / api_key_id grouping** — no chargeback.
- **No flex / priority service tier** — new customers already emit this.
- **Costs API cents-vs-dollars** — dividing by 100 is wrong on the current
  API shape. Spot-verify before release.
- **Image endpoints not pulled** — `/v1/organization/usage/images` has its
  own per-unit pricing; we don't hit it.
- **Audio endpoints not pulled** — realtime / audio-token models absent.
- **Moderations, vector_stores, code_interpreter_sessions** absent.
- **Pricing-table rot** — o4-mini exists in table but not o1-pro correctly,
  GPT-5 family missing entirely, Flex rates missing.
- **Fine-tuned model surcharge** not applied.
- **Silently returns `[]` on any exception** — hides legitimate errors.
- **No service-tier awareness in cost math.**

## Gaps Relative to Best Practice

1. Migrate cost source-of-truth to `/v1/organization/costs` — prices in
   dollars directly; usage endpoint stays for token analytics.
2. Add `input_cached_tokens` handling with 50/75/90% multipliers per
   model family.
3. Add `batch` dimension + dedicated batch pricing (50% off).
4. Add `project_id`, `user_id`, `api_key_id` grouping + dashboard drill-downs.
5. Pull `/v1/organization/usage/images` + `audio` + `moderations` + `vector_stores` + `code_interpreter_sessions`.
6. Nightly pricing sync from LiteLLM JSON.
7. Complete pricing for GPT-5.x family, o-series current gen, fine-tune
   surcharges.
8. Detect fine-tuned models (`ft:` prefix) and apply surcharge.
9. Proper service-tier awareness (standard / priority / flex).
10. Reasoning-token metadata for o-series models.
11. EU Data Zone flag.
12. Azure OpenAI detection and handoff to Azure connector.
13. Surface 401/403/404 distinctly in `test_connection` / `fetch_costs`.
14. Fix cents-vs-dollars mismatch if API now returns dollars.

## Roadmap

**Near-term (ship this week):**

- Swap primary source to `/v1/organization/costs`; usage endpoint as
  secondary.
- Verify and fix the `/100` cents conversion.
- Add `input_cached_tokens` with tiered discount math.
- Add batch dimension.
- Expand pricing table (GPT-5 family, fine-tune surcharges).
- Fix error handling (don't swallow everything).

**Medium (next month):**

- `project_id` + `user_id` + `api_key_id` grouping, frontend drill-downs.
- Image / audio / embedding endpoint coverage.
- Fine-tune detection + surcharge.
- LiteLLM pricing sync.
- Reasoning-token share metric.
- Batch-vs-standard savings recommendation.

**Long (quarter):**

- Unified "AI spend" dashboard across OpenAI + Anthropic + Gemini + Claude Code.
- Azure OpenAI connector reconciliation.
- EU Data Zone compliance flag.
- Anomaly detection on per-project burn rate.
- Realtime API cost breakdown (audio in vs audio out vs text).

## Change Log

- 2026-04-24: Initial knowledge-base created by overnight research run.
