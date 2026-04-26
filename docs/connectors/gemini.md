# Google Gemini / Vertex AI — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

Google's Gemini family (2.5 Pro / 2.5 Flash / 2.5 Flash Lite / 2.0 / 1.5 /
Imagen / Veo / embeddings) is consumable two ways: Google AI Studio
(`generativelanguage.googleapis.com`, consumer-focused, no first-party usage
API) and Vertex AI on Google Cloud (IAM-gated, billed via GCP billing).
Costly's `gemini_connector.py` is the most mature of the AI connectors — it
queries the BigQuery Cloud Billing export filtered to
`service.description = 'Vertex AI'` or `LIKE 'Generative Language API%'`,
uses a service account for auth, handles 401/403/404 classification, supports
context-tier pricing (Gemini 2.5 Pro's 200k threshold), and can refresh
pricing from the Cloud Billing SKU catalog. Current grade: **B+** — ahead of
the Anthropic/OpenAI connectors structurally, but missing explicit-vs-implicit
cache attribution, thinking-token surfacing, batch-discount detection, and
Imagen/Veo/embedding unit-price normalisation.

## Pricing Model (from vendor)

Canonical sources:

- Vertex AI: <https://cloud.google.com/vertex-ai/generative-ai/pricing>
- Gemini Developer API: <https://ai.google.dev/gemini-api/docs/pricing>
- Machine-readable: <https://ai.google.dev/gemini-api/docs/pricing.md.txt>

USD per million tokens, standard tier, list / non-batch.

### Gemini 2.5 family (2026-04)

| Model | Input ≤200k | Input >200k | Non-thinking output | Thinking output | Context |
|---|---|---|---|---|---|
| Gemini 2.5 Pro | $1.25 | $2.50 | $10.00 | $10.00 (output, thinking tokens billed same) | 1M (2M preview) |
| Gemini 2.5 Flash | $0.30 | $0.30 | $2.50 | $3.50 | 1M |
| Gemini 2.5 Flash Lite | $0.10 | $0.10 | $0.40 | $0.40 | 1M |

Gemini 2.5 Flash has the quirk that thinking-tokens (internal reasoning)
cost 1.4× the non-thinking output rate ($3.50/M vs $2.50/M). Gemini 2.5 Pro
bills thinking tokens at the same output rate. Source:
<https://rahulkolekar.com/gemini-pricing-in-2026-gemini-api-vs-vertex-ai-tokens-batch-caching-imagen-veo/>.

### Gemini 2.0 family

| Model | Input | Output |
|---|---|---|
| Gemini 2.0 Pro | $1.25 | $10.00 |
| Gemini 2.0 Flash | $0.10 | $0.40 |
| Gemini 2.0 Flash Lite | $0.075 | $0.30 |
| Gemini 2.0 Flash Image (gen) | $0.10 input | $30.00 / 1M image output tokens |

### Gemini 1.5 (legacy)

| Model | Input | Output |
|---|---|---|
| Gemini 1.5 Pro | $1.25 | $5.00 |
| Gemini 1.5 Flash | $0.075 | $0.30 |
| Gemini 1.5 Flash 8B | $0.0375 | $0.15 |
| Gemini 1.0 Pro (legacy) | $0.50 | $1.50 |

### Embeddings

| Model | Price |
|---|---|
| text-embedding-004 / text-embedding-005 / embedding-001 | $0.025 / M input |
| gemini-embedding-001 | $0.025 / M input |

### Image, video, audio

- **Imagen 3 / Imagen 4**: per-image price by resolution / quality (from ~$0.02/image for Standard to $0.08+ for Ultra). See Vertex pricing page.
- **Veo 3**: per-second of generated video; multi-tier pricing.
- **Gemini 2.0 Flash Image**: per-image output-token price ($30 / 1M image tokens).

### Pricing modifiers

- **Explicit context caching**: 90% discount on cached input for Gemini 2.5+; 75% for Gemini 2.0. PLUS storage cost: Gemini 2.5 Flash $1.00 / M tokens / hour; Gemini 2.5 Pro $4.50 / M / hour. Source:
  <https://docs.cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-overview>,
  <https://ai.google.dev/gemini-api/docs/caching>.
- **Implicit caching** (automatic, Gemini 2.5+): same per-token discount as
  explicit, but NO storage cost (cache-miss → cache-write is free; cache
  hit is the only chargeable event, at the read rate). Source:
  <https://yingtu.ai/en/blog/gemini-api-batch-vs-caching>.
- **Batch API**: 50% discount on input + output, 24h turnaround. Does NOT
  stack with caching (the 90%/75% discount replaces the 50% batch
  discount rather than multiplying). Source:
  <https://ai.google.dev/gemini-api/docs/batch>.
- **Minimum context for caching to engage**: 1,024 tokens for Gemini 2.5
  Flash; 4,096 for Gemini 2.5 Pro. Below threshold, caching is inactive.
- **Thinking tokens**: on Gemini 2.5 Flash, priced higher than non-thinking
  output. On Gemini 2.5 Pro, priced the same as output. Always billed as
  output — they count against the output token budget.
- **Provisioned Throughput**: enterprise tier offering capacity-reserved
  priority for a monthly fee; bills per-GSU (Generative AI Scale Unit).
- **Region pricing**: Most Gemini SKUs are priced uniformly across regions;
  a handful of experimental / ultra-low-latency SKUs have region premiums.
  Imagen and Veo vary more.

### AI Studio vs Vertex AI

- **AI Studio** (`generativelanguage.googleapis.com`) has a free tier
  (rate-limited) and a paid tier. The paid tier bills under a SKU on
  Google Cloud Billing as `Generative Language API`. There is NO first-party
  usage/cost _API_ for AI Studio independent of Cloud Billing.
- **Vertex AI** (`{region}-aiplatform.googleapis.com`) is fully enterprise
  (IAM, VPC-SC, CMEK, data-residency, audit logging). Billed under SKUs
  prefixed with `Vertex AI`.
- Prices are usually **identical** between AI Studio paid tier and Vertex
  AI at the same model / region, modulo compliance surcharges on certain
  Vertex SKUs.

## Billing / Usage Data Sources

### Primary

**BigQuery Cloud Billing Export (standard usage).**

- Table: `{billing_project}.{billing_dataset}.gcp_billing_export_v1_{BILLING_ACCOUNT}` where the billing account has dashes replaced with underscores.
- Docs: <https://cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/standard-usage>.
- Filter: `service.description = 'Vertex AI' OR service.description LIKE 'Generative Language API%' OR service.description = 'AI Platform'`.
- Auth: GCP service account with `bigquery.jobs.create` and
  `bigquery.tables.getData` on the billing dataset.
- Freshness: Standard export lands in ≈6h batches; detailed export lands
  per-day. For near-real-time, customers on Billing Reports in the Cloud
  Console have 15-min latency but no public API.
- Cost per run: BigQuery query pricing ($5/TB scanned) — trivially cheap for
  billing-export queries (the `gcp_billing_export_v1_*` table is partitioned
  on `usage_start_time` and we scan a day at a time).

### Secondary / Fallback

- **Cloud Billing API — `cloudbilling.googleapis.com/v1/services/{id}/skus`** —
  list current list prices. Used by our connector's
  `refresh_pricing_from_catalog()` to refresh the built-in table. Vertex AI
  service id: `services/F7F8-86C4-2D0E`; Generative Language API:
  `services/CCD8-9BF1-090E`. Source:
  <https://cloud.google.com/billing/docs/reference/rest/v1/services.skus>.
- **Detailed usage export**
  (`gcp_billing_export_resource_v1_{BILLING_ACCOUNT}`) — per-resource
  breakdown with `resource.name` (e.g. specific Vertex endpoint id).
  Useful for multi-tenant customers who need per-endpoint attribution.
  Docs: <https://docs.cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/detailed-usage>.
- **Vertex AI publisher/models endpoint** —
  `{region}-aiplatform.googleapis.com/v1/projects/{project}/locations/{region}/publishers/google/models`
  — only used for credential validation; does not carry usage.
- **`generativelanguage.googleapis.com/v1/models`** — AI Studio credential
  validation; no usage endpoint.
- **Cloud Monitoring** — custom metrics can be emitted per Vertex endpoint;
  not a primary cost source but useful for SLO correlation.
- **Vertex AI Pipelines `vertex-ai-pipelines-run-billing-id` label** — lets
  you filter the billing export for pipeline-specific cost roll-ups.
  Docs: <https://docs.cloud.google.com/vertex-ai/docs/pipelines/understand-pipeline-cost-labels>.

### Gotchas

- **Billing export is opt-in** — brand-new GCP orgs don't have it enabled.
  Our `test_connection()` returns a clear "Vertex AI credentials valid but
  BigQuery billing export is not configured" message, which is the right
  UX but users still need docs on the 10-minute setup:
  `Billing → Billing export → Configure`.
- **Billing account id normalisation** — dashes (`01ABCD-234567-89EFGH`)
  become underscores (`01ABCD_234567_89EFGH`) in the table name. Our
  connector handles this; users pasting the id with dashes are a common
  support ticket.
- **`usage_start_time` partitioning** — query must filter on
  `DATE(usage_start_time)` not `usage_date` for the partition filter to
  engage. Our connector does this correctly.
- **Credits in billing export** — Google applies free-tier credits and
  committed-use discounts via the `credits` array. Net cost is
  `cost + SUM(credits.amount)` where credits are usually negative. Our
  connector computes this correctly.
- **SKU description is unstructured** — no clean `model` field in the billing
  export. We classify via substring match on the SKU description. This
  misses new models until we update `MODEL_PRICING` / `_guess_model`.
- **Implicit vs explicit caching indistinguishable in the billing export**
  — both roll up under the same SKU. Differentiation requires response-level
  logging or Cloud Monitoring metrics.
- **Thinking-token share indistinguishable in billing** — they're lumped
  into output tokens on the billing SKU. The only way to separate is per-
  response `usage_metadata.thoughts_token_count`.
- **AI Studio free tier** leaks into the billing export as $0 usage rows
  which can drown the signal if the customer has heavy free-tier traffic.
- **Vertex AI on Claude / Llama / Mistral** — third-party models on Vertex
  are billed differently (Claude on Vertex uses Anthropic's price × Vertex
  margin, for instance). Don't conflate Gemini SKUs with third-party model
  SKUs even if they show up under `service.description = 'Vertex AI'`.
- **Project isolation** — billing export rows carry `project.id`; orgs with
  many projects should always filter or group by project.
- **Region pricing variance** — most Gemini pricing is region-uniform, but
  Imagen, Veo, and a few GA SKUs vary. Rely on the SKU's unit price rather
  than a per-token table when possible.

## Schema / Fields Available

From `gcp_billing_export_v1_*`:

| Field | Type | Semantic |
|---|---|---|
| `usage_start_time`, `usage_end_time` | timestamp | Usage window |
| `service.description` | str | `"Vertex AI"`, `"Generative Language API"`, `"AI Platform"` |
| `service.id` | str | Stable GCP service id |
| `sku.description` | str | Human-readable SKU ("Gemini 2.5 Pro Input Tokens ≤200K", …) |
| `sku.id` | str | Stable SKU id (e.g. `F7F8-86C4-2D0E.0001`) |
| `project.id`, `project.name` | str | GCP project |
| `location.location`, `location.region`, `location.zone` | str | Geography |
| `labels` (array of key/value) | array | Custom labels; `vertex-ai-pipelines-run-billing-id` among others |
| `system_labels` | array | GCP-managed labels |
| `usage.amount` | num | Quantity in `usage.unit` |
| `usage.unit` | str | `"tokens"`, `"characters"`, `"images"`, `"second"`, `"[tokens]/1000"` |
| `cost` | num | Gross cost in `currency` |
| `currency` | str | Usually `"USD"` |
| `credits` | array | Each has `amount` (negative) and `type` |
| `invoice.month` | str | Invoice month |

From per-response `usage_metadata`:

| Field | Type | Semantic |
|---|---|---|
| `prompt_token_count` / `promptTokenCount` | int | Standard input |
| `candidates_token_count` / `candidatesTokenCount` | int | Visible output |
| `cached_content_token_count` / `cachedContentTokenCount` | int | Cached input, 0.25× |
| `thoughts_token_count` / `thoughtsTokenCount` | int | Thinking tokens (billed as output) |
| `tool_use_prompt_token_count` / `toolUsePromptTokenCount` | int | Tool-use prompt (billed as input) |
| `total_token_count` / `totalTokenCount` | int | Vendor-computed sum |

## Grouping Dimensions

From billing export — everything that's a column is a dimension:

- `project.id` — chargeback.
- `location.region` — residency / cost comparison.
- `sku.description` / `sku.id` — model family proxy.
- `service.description` — separates Vertex from AI Studio paid tier.
- `labels.*` — custom (teams, envs, features, pipeline run ids).
- `invoice.month` — monthly rollup.

From per-response metadata (if we were to sidecar Messages-API logs):

- model, region, cached vs non-cached, thinking vs non-thinking, tool-use.

## Open-Source Tools Tracking This Platform

| Tool | URL | Approx stars | License | What it tracks | Source |
|---|---|---|---|---|---|
| **LiteLLM** | <https://github.com/BerriAI/litellm> | 19k+ | MIT | Proxy/SDK wrapping Vertex + Gemini API; emits `response_cost`; sinks to Prometheus/BigQuery/ClickHouse | SDK wrap |
| **LiteLLM pricing JSON** | <https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json> | (same repo) | MIT | Gemini SKU pricing including context-tier thresholds | Manual PRs |
| **Helicone** | <https://github.com/Helicone/helicone> | ~3k | Apache-2.0 | Proxy / dashboards / caching | Proxy |
| **Langfuse** | <https://github.com/langfuse/langfuse> | ~7k | MIT / commercial | Trace + cost; natively supports Vertex and Gemini SDK | SDK |
| **Arize Phoenix + OpenInference** | <https://github.com/Arize-ai/phoenix>, <https://github.com/Arize-ai/openinference> | ~4k / ~800 | Elastic-2.0 / Apache-2.0 | OTEL instrumentation for Gemini SDK | OpenInference |
| **OpenLLMetry / Traceloop** | <https://github.com/traceloop/openllmetry> | ~2.5k | Apache-2.0 | OTEL SDK with Vertex support | OTEL |
| **stevenaldinger/vertex-ai-google-cloud-billing** | <https://github.com/stevenaldinger/vertex-ai-google-cloud-billing> | ~50 | MIT | Vertex AI + BigQuery billing export reference impl | BigQuery |
| **PostHog LLM analytics** | <https://github.com/PostHog/posthog> | ~20k | MIT | Product-analytics LLM cost cards | SDK |
| **Portkey Gateway** | <https://github.com/Portkey-AI/gateway> | ~5k | MIT | AI gateway with provider routing | Gateway |
| **tokscale** | <https://github.com/junhoyeo/tokscale> | ~800 | MIT | Covers Gemini CLI alongside other coding agents | Per-tool |
| **TokenTracker** | <https://github.com/mm7894215/TokenTracker> | ~400 | MIT | Multi-agent dashboard incl. Gemini CLI | Local |
| **coding_agent_usage_tracker** | <https://github.com/Dicklesworthstone/coding_agent_usage_tracker> | ~200 | MIT | Unified quota incl. Gemini | Per-tool |

The Gemini / Vertex ecosystem has fewer dedicated OSS cost trackers than the
Anthropic world. The BigQuery billing export is the canonical path, and most
practitioners either hand-roll SQL or use LiteLLM as a proxy rather than
building a dedicated tool.

## How Competitors Handle This Platform

- **Vantage (vantage.sh)** — Supports Google (Gemini 1.5/2.0) in its AI spend
  intelligence product. Pulls per-token data via SDK wrapping rather than
  billing export. Source:
  <https://www.vantage.sh/blog/top-platforms-for-managing-ai-costs>.
- **CloudZero** — Ingests GCP billing via Cost Explorer-equivalent + direct
  BigQuery pull. Gemini/Vertex SKUs appear as first-class cost lines in the
  GCP cost allocation view. No special Gemini-tuned dashboard noted.
  Source: <https://www.cloudzero.com/blog/ai-cost-management/>.
- **Finout** — GCP Cloud Billing ingestion via CUR-equivalent; Vertex AI and
  Generative Language API line items rolled into MegaBill alongside other
  AI providers.
- **Datadog CCM** — Full GCP cost integration. LLM Observability covers
  Gemini via OpenAI-compatible proxying. No dedicated Vertex AI Cost
  Management page as of 2026-04, but CCM GCP views surface the SKUs.
  Source: <https://www.datadoghq.com/blog/manage-ai-cost-and-performance-with-datadog/>.
- **Revefi** — Recently added BigQuery Gemini cost messaging; no first-
  class Vertex connector documented.
- **nOps (nops.io)** — Vertex AI Pricing guide published 2026; no
  first-class connector.
- **Ternary (ternary.app)** — Formerly FinOps-focused; mentions FinOps for
  AI and has a GCP connector.
- **Select.dev, Keebo, Espresso AI, Chaos Genius/Flexera** — Warehouse only.
  BigQuery cost is relevant here as a compute source (not Gemini SKUs).
- **Amberflo, Cloudchipr** — Generic cloud cost, no Gemini-specific
  analytics.

The commercial frontier on Vertex AI is (a) joint GCP cost + LLM cost in one
dashboard, (b) BigQuery-billing-export-first (which Costly already does),
and (c) labels-driven cost allocation (pipeline run, team, env).

## Books / Published Material / FinOps Literature

- **Cloud FinOps** (Storment & Fuller, O'Reilly, 2nd ed) —
  <https://www.oreilly.com/library/view/cloud-finops-2nd/9781492098348/>.
- **FinOps Foundation — FinOps for AI Overview** —
  <https://www.finops.org/wg/finops-for-ai-overview/>.
- **FinOps Foundation — Choosing an AI Approach and Infrastructure Strategy** —
  <https://www.finops.org/wg/choosing-an-ai-approach-and-infrastructure-strategy/>.
- **FinOps Foundation — Effect of Optimization on AI Forecasting** —
  <https://www.finops.org/wg/effect-of-optimization-on-ai-forecasting/>.
- **Google Cloud Documentation — Structure of Detailed data export** —
  <https://docs.cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/detailed-usage>.
- **Google Cloud Documentation — Example queries for Cloud Billing export** —
  <https://docs.cloud.google.com/billing/docs/how-to/bq-examples>.
- **Google Cloud Documentation — Context caching overview (Vertex AI)** —
  <https://docs.cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-overview>.
- **Google AI Dev — Context caching (Gemini API)** —
  <https://ai.google.dev/gemini-api/docs/caching>.
- **Google AI Dev — Pricing (machine-readable)** —
  <https://ai.google.dev/gemini-api/docs/pricing.md.txt>.
- **Matias Coca — AI Cost Tracking on GCP: A Practical Guide to Vertex AI,
  Gemini API, and Model Spend** (Medium, March 2026) —
  <https://medium.com/@cocamatias/ai-cost-tracking-on-gcp-a-practical-guide-to-vertex-ai-gemini-api-and-model-spend-63b3c87d8ee4>.
  The single best practitioner guide available for this platform.
- **Google Developer Forums — GCP Billing Export to BigQuery: Quick Guide
  to Tracking AI costs** —
  <https://discuss.google.dev/t/gcp-billing-export-to-bigquery-quick-guide-to-tracking-ai-costs/318584>.
- **nOps — Vertex AI Pricing: The Complete 2026 Guide to Costs, Hidden
  Fees, and Savings** — <https://www.nops.io/blog/vertex-ai-pricing/>.
- **Finout — Gemini Pricing in 2026** —
  <https://www.finout.io/blog/gemini-pricing-in-2026>.
- **TokenMix — Google Vertex AI Pricing 2026: Gemini, Claude, and Llama
  on Vertex** — <https://tokenmix.ai/blog/vertex-ai-pricing>.
- **TokenMix — Google Gemini API Pricing 2026** —
  <https://tokenmix.ai/blog/google-gemini-api-pricing>.
- **CloudZero — Gemini AI Pricing: What You'll Really Pay In 2025** —
  <https://www.cloudzero.com/blog/gemini-pricing/>.
- **Rahul Kolekar — Gemini Pricing in 2026: Gemini API vs Vertex AI Costs,
  Tokens, Caching, Batch, Imagen, Veo** —
  <https://rahulkolekar.com/gemini-pricing-in-2026-gemini-api-vs-vertex-ai-tokens-batch-caching-imagen-veo/>.
- **YingTu — Gemini API Batch vs Context Caching: Complete Cost
  Optimization Guide 2026** —
  <https://yingtu.ai/en/blog/gemini-api-batch-vs-caching>.
- **AI Free API — Gemini API Context Caching: Complete Guide to Reducing
  Costs by Up to 90% 2026** —
  <https://www.aifreeapi.com/en/posts/gemini-api-context-caching-reduce-cost>.
- **GeminiPricing.com — Vertex AI Pricing Explained 2026** —
  <https://geminipricing.com/vertex-ai-pricing>.
- **MetaCTO — Gemini API Pricing 2026** —
  <https://www.metacto.com/blogs/the-true-cost-of-google-gemini-a-guide-to-api-pricing-and-integration>.
- **Google Cloud FinOps Hub** — built-in tool in the Google Cloud console
  that surfaces BigQuery-billing-export-derived insights.

There is **no printed book dedicated to Vertex AI cost management**, but
Google Cloud's "Cost management best practices" whitepaper (PDF on
cloud.google.com) covers the framework.

## Vendor Documentation Crawl

- **Vertex AI pricing page** — <https://cloud.google.com/vertex-ai/generative-ai/pricing>.
- **Gemini API pricing page** — <https://ai.google.dev/gemini-api/docs/pricing>.
- **Pricing (machine-readable)** — <https://ai.google.dev/gemini-api/docs/pricing.md.txt>.
- **Billing export docs (standard)** —
  <https://cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/standard-usage>.
- **Billing export docs (detailed)** —
  <https://docs.cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/detailed-usage>.
- **Example billing queries** —
  <https://docs.cloud.google.com/billing/docs/how-to/bq-examples>.
- **Cloud Billing API — SKUs reference** —
  <https://cloud.google.com/billing/docs/reference/rest/v1/services.skus>.
- **Context caching — Vertex AI** —
  <https://docs.cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-overview>.
- **Context caching — Gemini API** —
  <https://ai.google.dev/gemini-api/docs/caching>.
- **Batch API** — <https://ai.google.dev/gemini-api/docs/batch>,
  <https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/batch-prediction-api>.
- **Thinking / reasoning** —
  <https://ai.google.dev/gemini-api/docs/thinking>.
- **Usage metadata reference** —
  <https://ai.google.dev/api/generate-content#UsageMetadata>.
- **Vertex AI Pipelines cost labels** —
  <https://docs.cloud.google.com/vertex-ai/docs/pipelines/understand-pipeline-cost-labels>.
- **Provisioned Throughput** —
  <https://cloud.google.com/vertex-ai/generative-ai/docs/provisioned-throughput>.
- **Release notes** —
  <https://cloud.google.com/vertex-ai/docs/release-notes>. Cadence is
  roughly weekly for Vertex AI; new Gemini models announced at
  DeepMind events typically follow within a few weeks.
- **Region availability** —
  <https://cloud.google.com/vertex-ai/generative-ai/docs/learn/locations>.
  Gemini models available in US, EU, Japan, India, etc.; availability varies
  by model family (2.5 Pro in fewer regions than 2.0 Flash).
- **SLA / compliance** — <https://cloud.google.com/terms/service-terms>,
  <https://cloud.google.com/security/compliance>. Vertex AI inherits GCP's
  compliance posture: SOC 1/2/3, ISO 27001/17/18/701, PCI, HIPAA BAA, FedRAMP
  High. AI Studio's paid tier has the same GCP-level compliance.

## Best Practices (synthesized)

1. **BigQuery billing export is the ground truth.** Anything else is a
   sidecar. Our connector gets this right.
2. **Filter on `DATE(usage_start_time)`** so BigQuery engages the
   partition filter — queries go from 1-minute scans to sub-second.
3. **Always union `'Vertex AI'`, `'Generative Language API%'`, and
   `'AI Platform'`** in the service-description filter. Google has used
   all three labels over time; a query on only one misses data.
4. **Include credits** in net cost math (`cost + SUM(credits.amount)`).
   Free-tier and committed-use credits show up here.
5. **Group by `project.id`** for chargeback.
6. **Use labels for cost allocation** — `vertex-ai-pipelines-run-billing-id`
   is built-in; customers should add their own (team, env, feature) via
   endpoint labels.
7. **Sidecar per-response `usage_metadata`** when you need thinking-token
   share, cache hit rate, or tool-use split — the billing export can't
   tell you.
8. **Context-tier pricing is only on Gemini 2.5 Pro** (200k threshold).
   Don't apply it to 2.5 Flash or 2.0 families.
9. **Honor the 1024 / 4096 token caching minimums** when estimating cache
   savings — below threshold, caching doesn't engage.
10. **Batch does NOT stack with caching** on Gemini. The larger discount
    applies, not the product.
11. **Refresh pricing from Cloud Billing SKU catalog** nightly if the SA
    has `cloudbilling.services.list`. Our connector already has
    `refresh_pricing_from_catalog()`.
12. **Separate Imagen / Veo / Embedding SKUs** — they're not per-token
    and mixing them inflates per-token metrics.
13. **AI Studio free tier leaks** — filter out zero-cost rows if the
    customer only wants to see paid usage.
14. **Third-party models on Vertex (Claude, Llama, Mistral)** — don't
    conflate with Gemini SKUs. Check SKU descriptions for the model family.

## Costly's Current Connector Status

**File:** `backend/app/services/connectors/gemini_connector.py`

~890 lines. Structurally the most mature of the AI connectors. What it does:

- Accepts `api_key` (AI Studio), `service_account_json`, `project_id`,
  `region`, `billing_project`, `billing_dataset`, `billing_account_id`,
  `billing_table`, `pricing_overrides`.
- Detects three credential modes:
  - `use_vertex` — SA + project
  - `has_billing_export` — SA + project + billing dataset + billing account
  - AI Studio only (api_key)
- `test_connection` branches appropriately:
  - AI Studio only → hits `/v1/models` and returns a clear "not sufficient
    for cost tracking" message.
  - Vertex SA but no billing export → hits publisher/models endpoint and
    reports "credentials valid but billing export not configured".
  - Full config → dry-runs a BigQuery query against the billing export.
- `fetch_costs` runs a parameterised SQL against
  `gcp_billing_export_v1_{BILLING_ACCOUNT}` filtering by Vertex AI /
  Generative Language API / AI Platform service descriptions, groups by
  `(usage_date, sku, project, region)`, sums `cost + credits`, returns
  UnifiedCost rows.
- Proper HTTP error classification (401 / 403 / 404 / "API disabled").
- Service-account OAuth2 token generation with `google-auth` preferred,
  fallback to hand-rolled PyJWT bearer-assertion flow.
- Pricing table includes context-tier awareness for Gemini 2.5 Pro
  (`input_over_200k`, `output_over_200k`, `context_tier_tokens=200000`).
- `TokenUsage` dataclass captures prompt / candidates / cached_content /
  thoughts / tool_use_prompt — parses both camelCase (Vertex) and snake_case
  (google-generativeai) keys.
- `estimate_cost` applies `CACHE_READ_MULTIPLIER=0.25` (Gemini 2.0 tier;
  should be 0.10 for 2.5+ — gap) and context-tier pricing.
- `refresh_pricing_from_catalog()` best-effort pulls Cloud Billing SKU
  catalog.

What's working:

- Correct primary data source (BigQuery billing export).
- Robust credential detection and graceful degradation.
- Service-description filter covers all three historical labels.
- Credits included in net cost.
- Partition filter engages (`DATE(usage_start_time)`).
- Project + region + SKU retained in metadata.
- Longest-prefix pricing resolution.
- HTTP error classification surfaces permission / disabled-API failures.

What's broken or missing:

- **`CACHE_READ_MULTIPLIER = 0.25`** is the Gemini 2.0 rate. Gemini 2.5+ is
  0.10 (90% off). Either branch by model family or move to pulling rates
  from the SKU catalog.
- **Cache storage cost not modelled** — explicit caches cost $1.00/M/hr
  (Flash) or $4.50/M/hr (Pro) to store. Users who don't delete caches can
  burn $24+/day per 1M-token cache. Billing export shows this as a
  separate SKU (`... cache storage`), but our SKU classifier doesn't flag
  it.
- **Thinking tokens are billed differently on 2.5 Flash** — 1.4× output
  rate — and our code uses `THINKING_TOKEN_MULTIPLIER = 1.00` flat. OK for
  Pro, wrong for Flash.
- **Batch SKUs not classified separately** — they carry `sku.description`
  containing "Batch"; we should add a SKU classifier for it.
- **Imagen / Veo SKUs fall through the per-token pricing fallback** — we
  classify them as `ai_inference` correctly but the model-name guess may
  be off. Per-image / per-second pricing not modelled in `estimate_cost`
  — fine for billing-export-derived cost (we pass through the billing
  export dollar value), but it matters for any forward-looking estimate.
- **Third-party models on Vertex (Claude, Llama, Mistral)** are billed to
  Vertex service and will appear in our connector's rollup — but they're
  not Gemini. Needs a secondary classifier so users see "Claude on Vertex"
  distinctly.
- **`pricing_overrides` exists but not wired into cost recomputation path**
  — Costly today doesn't recompute cost from tokens; it takes the billing
  export's dollar figure. That's correct. But if we ever need to estimate
  future cost (budget forecasting), the override pathway is necessary.
- **No Cloud Monitoring / per-response sidecar** — can't split cache hit rate,
  thinking share, or tool-use share without it.
- **`refresh_pricing_from_catalog` uses stale service ids** — `services/F7F8-86C4-2D0E`
  (Vertex AI) and `services/CCD8-9BF1-090E` (Generative Language API) are
  plausible but should be auto-discovered via the service catalog list
  endpoint to avoid future breakage.
- **Detailed export table** (`gcp_billing_export_resource_v1_*`) not
  supported — detailed per-endpoint attribution unavailable.
- **Provisioned Throughput (GSU)** billing line not surfaced as a separate
  metric.
- **No labels-based grouping** — customers using endpoint labels for team
  attribution lose that dimension in the unified view.

## Gaps Relative to Best Practice

1. Fix cache-read multiplier — branch by model generation (0.10 for 2.5+, 0.25 for 2.0, 0.10 for 1.5 legacy).
2. Model cache storage cost separately (SKU classifier + `cache_storage_cost_usd` metadata).
3. Branch thinking-token pricing by model family (2.5 Flash = 1.4× output; Pro = 1.0× output).
4. Add batch SKU classification + surface batch-vs-real-time split.
5. Classify third-party models on Vertex (Claude on Vertex, Llama on Vertex, Mistral on Vertex) as a different `service` slug.
6. Detailed billing export support for per-endpoint attribution.
7. Labels-based grouping (`labels.team`, `labels.env`, etc.).
8. Per-response `usage_metadata` sidecar capability (future: ingest logs from Cloud Logging with response metadata to split thinking / cache / tool-use).
9. Provisioned Throughput (GSU) detection.
10. Imagen / Veo unit pricing in the forward-estimate path.
11. Auto-discover Cloud Billing service ids instead of hardcoding.
12. Surface the `cache minimum context tokens` rule (1024 Flash / 4096 Pro) in recommendations.
13. Flag AI Studio free-tier rows distinctly.

## Roadmap

**Near-term (ship this week):**

- Fix `CACHE_READ_MULTIPLIER` per model family.
- Fix `THINKING_TOKEN_MULTIPLIER` per model family.
- Classify Batch SKUs; emit `metadata.batch = True`.
- Classify third-party models on Vertex; emit `service = "claude_on_vertex"` / `"llama_on_vertex"` / `"mistral_on_vertex"`.
- Add `cache storage` SKU classifier and surface as its own metric.

**Medium (next month):**

- Support detailed billing export table for per-endpoint / per-resource
  attribution.
- Labels-based grouping (with a pass-through into `metadata.labels`).
- Provisioned Throughput detection + alert ("you're under-utilising your
  provisioned GSU by 60%").
- Imagen / Veo / embedding per-unit pricing in the forward-estimate path.
- Auto-discover service ids from catalog.
- Nightly SKU catalog pricing refresh (we have the method, wire it into
  the scheduler).

**Long (quarter):**

- Sidecar Cloud Logging ingestion for per-response `usage_metadata` — unlocks
  cache hit rate, thinking share, tool-use share, which the billing export
  can't expose.
- Unified "AI spend" dashboard across Gemini + Anthropic + OpenAI + Claude Code.
- Forecasting: Provisioned Throughput vs pay-as-you-go breakeven analysis.
- Vertex AI Pipelines cost attribution (via `vertex-ai-pipelines-run-billing-id`
  label), with a drill-down to pipeline runs.
- AI Studio (paid tier) standalone view for users who don't run on Vertex.
- Multi-project aggregation — single connector config spanning N projects.
- Anomaly detection on per-project / per-region spend.

## Change Log

- 2026-04-24: Initial knowledge-base created by overnight research run.

## Re-recording contract fixtures

Contract tests for this connector live at `backend/tests/contract/test_gemini.py`
and load JSON fixtures from `backend/tests/fixtures/gemini/`. The fixtures are
intentionally hand-written from the public API docs so they don't leak any
real account data — every contributor can run the suite offline.

To capture fresh fixtures against a real Vertex AI account when the API
schema drifts, set credentials and run pytest with `--record-mode=once`:

```bash
cd backend
GCP_SA_JSON='...' GCP_PROJECT=... GCP_BILLING_DATASET=billing_export \
    pytest tests/contract/test_gemini.py --record-mode=once
```

Then sanitize the captured JSON (strip account ids, emails, tokens) before
committing. See `docs/testing/contract-tests.md` for the philosophy.


