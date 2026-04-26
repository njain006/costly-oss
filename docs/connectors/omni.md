# Omni — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

Omni (omni.co) is a Y Combinator-era startup BI platform founded in 2022 by ex-Looker / ex-Stitch leaders (Colin Zima, Jamie Davidson, Chris Merrick). It's pitched as "Looker's semantic governance plus Tableau's ad-hoc flexibility." As of 2026-04 it's still in fast-growth mode with a **mostly opaque, sales-led pricing** model and a **deliberately minimal public API** — the published REST API covers identity and embedding, not query-level usage. Usage telemetry is surfaced through Omni's **System Activity** workspace (an in-product semantic model over internal logs), modeled similarly to Looker's `system__activity`. Public pricing anchors cluster around **$350–$500/paid seat/year** for the Standard plan with Viewers free, and enterprise "contact us" tiers higher. Costly's current `OmniConnector` uses `api_key` bearer auth against `/api/v0/connections`, `/api/v0/users`, `/api/v0/queries` — but `/api/v0/queries` is **not a documented public endpoint** and will almost certainly 404 on most tenants. This doc flags that bug and maps the real API surface.

## Pricing Model

Omni does not fully publish SKU pricing. Known data points (public site + third-party analysis, 2025–2026):

- **Viewer seats**: **free** (unlimited consumers). This is Omni's biggest marketing differentiator vs Looker.
- **Standard / paid seats** (authoring — "Querier" / "Developer"): **~$350–$500/user/year** based on Vendr benchmarks and Omni's marketing ("starts around $40/month/developer").
- **Embedded / Omni Embed**: separate SKU, **metered on sessions or MAUs** for external-facing apps.
- **Enterprise**: SSO/SCIM/IP allowlisting/audit adds a platform fee, quoted bespoke.
- **Included features**: semantic layer, Excel export, AI ("Blobby"), Git workflow, dbt integration, branching.
- Omni emphasizes that there is no separate "Developer" tier markup like Looker — all paid seats can author.

Sources:

- https://omni.co/pricing — free trial CTA, no numbers (as of last crawl)
- https://omni.co/blog/omni-pricing-and-packaging — founder blog post on philosophy (indicative, no prices)
- Vendr "Omni Analytics pricing"
- G2 and Gartner Peer Insights — periodic user-reported ACV data
- Data Engineering Podcast Ep. "Inside Omni with Colin Zima" — discusses packaging rationale
- Sacra.com teardown (2024/2025) — revenue and ACV estimates

**Opacity note:** Very high. Any Costly estimate should be flagged "calibrate with customer invoice".

## Billing / Usage Data Sources

### Primary

- **Omni REST API** — base `https://<customer>.omniapp.co/api/`. Published (documented) endpoints live under `/api/unstable/` and some under `/api/v1/`. Mature public surface:
  - `GET /api/unstable/users` — user roster with role (`ADMIN`, `MEMBER`, `VIEWER`, etc.). Paginated via cursor `pageToken`.
  - `GET /api/unstable/connections` — warehouse connections used by Omni.
  - `GET /api/unstable/documents` — dashboards / workbooks.
  - `GET /api/unstable/models` — semantic models.
  - `GET /api/unstable/folders` — folders.
  - Embed endpoints: `POST /api/unstable/embed/sso` — signed URL for embed; `GET /api/unstable/embed/tenants` — multi-tenant embedded.
  - Groups, memberships, API keys — admin endpoints.
- **System Activity workspace (in-product)** — Omni ships a read-only semantic model called **"System Activity"** (or "Admin / Usage") available to admins. Tables exposed as Omni topics:
  - `query_runs` — every query run: user, document, runtime, rows, source (ui/api/embed).
  - `documents` — all documents (dashboards + workbooks).
  - `users` — user table including last-login.
  - `sessions` — login sessions.
  - `dashboard_views` — per-dashboard view counts.
  - `model_commits` — Git-style commits on the semantic model (audit trail).
  - `export_runs` — downloads / scheduled sends.
- **System Activity via SQL**: some Enterprise customers can point a BI/SQL client at Omni's internal analytics warehouse (hosted read-replica). Not universal.
- **Audit log export**: Enterprise customers can configure a webhook or S3 destination for audit events.

### Secondary

- **Connection-side warehouse** — since Omni pushes queries to the customer's warehouse, **the warehouse's own query-history is the most authoritative per-query cost source**. The Omni query is typically tagged with `application_name = 'omni'` or comments containing `omni.co` / document ID, which the Snowflake/BigQuery/Redshift/Postgres connectors can pattern-match.
- **Omni's in-app Usage page** — admin-only UI with top documents, top users, query counts.
- **Blobby (AI) usage** — separate telemetry for AI-assisted queries, surfaced via System Activity if enabled.
- **Omni status / admin SSO logs** — for signin events.

### Gotchas

- **API versioning is messy**: at various times Omni has exposed `/api/v0/`, `/api/v1/`, and `/api/unstable/`. As of 2026-04 the **officially documented** prefix is `/api/unstable/` (per docs.omni.co), with `/api/v1/` reserved for eventual GA. **Costly's code uses `/api/v0/`** — this is the old path and may 404 on current tenants. Validate against the customer's actual endpoint before shipping.
- **`/api/v0/queries` does not exist publicly** — there is no documented public endpoint that returns per-query history. The only way to get per-query usage today is:
  1. System Activity topic via an authenticated Omni UI session (not exposed via REST), or
  2. Warehouse-side query-history filtering by Omni's SQL tags, or
  3. Audit log webhook (enterprise).
- **Auth is bearer-token** on `Authorization: Bearer <api_key>`. API keys are admin-scoped and tenant-scoped.
- **Rate limits** — not published; conservative 10 req/sec.
- **Tenant subdomain** required (`<tenant>.omniapp.co`). Customer must supply full URL.
- **Embed APIs** use HMAC-signed URLs, not bearer tokens — different flow.
- **Pagination**: cursor-based (`pageToken`). Early responses sometimes returned a bare JSON array (Costly's code tolerates both).
- **Role vocabulary drift**: historical roles included `CONSUMER`, `QUERIER`, `DEVELOPER`, `ADMIN`; newer vocabulary is `VIEWER`, `MEMBER`, `ADMIN`. The mapping to seat tier for billing needs a lookup table.
- **AI cost**: Blobby AI queries may incur OpenAI/Anthropic cost that Omni absorbs (Standard) or passes through (Enterprise) — not visible via API.
- **Small dataset** — Omni deployments are smaller than Looker/Tableau, so per-tenant telemetry is low volume; don't over-engineer.
- **Young product** — endpoints change. Pin to `/api/unstable/` but **test in the customer tenant first**.

## Schema / Fields Available

Via the REST API (unstable):

| Endpoint | Key fields |
|---|---|
| `/api/unstable/users` | `id`, `email`, `displayName`, `role`, `createdAt`, `lastLoginAt`, `disabled` |
| `/api/unstable/connections` | `id`, `name`, `dialect` (snowflake/bigquery/postgres/redshift/duckdb), `createdAt` |
| `/api/unstable/documents` | `id`, `name`, `type` (dashboard/workbook), `owner`, `folderId`, `connectionId`, `createdAt`, `updatedAt` |
| `/api/unstable/models` | `id`, `name`, `connectionId` |
| `/api/unstable/folders` | `id`, `name`, `parentId` |

Via System Activity topics (in-product, not REST):

| Topic | Fields |
|---|---|
| `query_runs` | `id`, `user_id`, `document_id`, `model`, `topic`, `runtime_ms`, `rows_returned`, `source`, `created_at`, `connection_id`, `sql_text` |
| `dashboard_views` | `dashboard_id`, `user_id`, `viewed_at` |
| `exports` | `document_id`, `user_id`, `format`, `created_at` |
| `sessions` | `user_id`, `started_at`, `ended_at`, `user_agent` |
| `model_commits` | `model_id`, `user_id`, `message`, `created_at` |

## Grouping Dimensions

- **Per-user** — `user_id` + `role`.
- **Per-document** (dashboard or workbook).
- **Per-folder** (usually aligned to team/project).
- **Per-topic / model** — the semantic-layer analog to Looker Explore.
- **Per-connection** — **critical** for warehouse cost join.
- **Per-source** — ui / api / embed / scheduled.
- **Per-role tier** — Viewer (free) vs paid.
- **Per-document type** — dashboard vs workbook.

## Open-Source Tools

The Omni ecosystem is young and OSS tooling is thin.

- **omni-community-samples** — community-shared Omni workspaces and model examples (omni.co/blog links).
- **Omni's CLI** — `omni-cli` — semi-official for Git-sync of semantic models; watch omni.co docs for public release.
- **dbt integration** — Omni natively reads dbt manifests; `dbt docs` and `dbt_project_evaluator` remain the OSS lineage backbone.
- **Catalog tools**: DataHub, OpenMetadata, Atlan, Secoda — as of 2026-04, native Omni ingesters are nascent; most shops point DataHub's SQL-based lineage at the warehouse and pattern-match Omni's query tags.
- **Examples in Omni blog**: https://omni.co/blog — "Omni's own analytics on Omni" posts are effectively the reference architecture.
- **Steampipe / dlt-hub** — generic REST ingesters can wrap the Omni unstable API for warehouse-side storage.
- **Zima/Davidson/Merrick** GitHub gists — occasional small utilities.

Because Omni is proprietary semantic, there is no `lkml`-style parser yet for its model files.

## How Competitors Handle Omni

- **Omni's own Observability / Admin** — benchmark. The in-product System Activity workspace is what Costly needs to match or wrap.
- **None of the major cost-observability vendors** (CloudZero, Vantage, Unravel, Bluesky) ship a named Omni integration as of 2026-04. This is an open opportunity.
- **Early Omni customers publish "how we use Omni" blog posts** — Ramp, Census, Hightouch-adjacent shops. These describe manual warehouse-tag-based attribution, which is exactly the pattern Costly should adopt.
- **Looker / Tableau alternative BIs** (ThoughtSpot, Sigma, Hex, Mode, Preset/Superset) — their pattern applies here: pull users+documents from REST, pull query history from warehouse, join by SQL tag / connection.
- **dbt Explorer** — tracks model→dashboard exposures; Omni documents can be tagged as exposures for cross-tool lineage.
- **Hex** — another modern BI with similar "warehouse does the compute, we bill per seat" model; Hex publishes a more detailed REST API (including `/api/v1/runs`) — a useful comparison for what Omni's API may grow into.
- **Mode / Sigma / Preset** — all expose more usage via REST than Omni; lift-and-shift patterns work here.

Dimensions to track: seat count (free + paid), per-document views, per-query runtime, per-user activity, per-connection warehouse cost share, AI-query counts.

## Books / Published Material

No published books on Omni yet (too new).

- **Omni blog** — https://omni.co/blog — authoritative. Notable:
  - "Introducing Omni" (Colin Zima, 2023)
  - "Omni's approach to the semantic layer"
  - "Git-based model development"
  - "Omni pricing and packaging"
  - "AI in BI: Blobby"
  - "Embedded analytics with Omni"
- **Podcast episodes**:
  - **Analytics Engineering Podcast** (Tristan Handy) — multi-episode arc with Colin Zima.
  - **Data Engineering Podcast** (Tobias Macey) — founder-interview episode.
  - **The Data Stack Show** (Eric Dodds, Kostas Pardalis) — Colin Zima appearance.
  - **Catalog & Cocktails** — Tim Gasper — Chris Merrick appearance.
- **Founder history**: Looker's modeling philosophy (Lloyd Tabb) and Stitch's ETL philosophy (Jake Stein, Chris Merrick) inform Omni's design — the Looker book corpus is transferable.
- **Adjacent reading** (cross-BI): "Storytelling with Data" (Knaflic), "The Big Book of Dashboards" (Wexler/Shaffer/Cotgreave), "The Unified Star Schema" (Canter/Kimball) — modeling foundation.
- **Jamie Davidson talks** (YouTube) — product strategy / semantic layer.
- **Analytics Engineering roundup** (Madison Schott, Claire Carroll) — recurring newsletter that reviews Omni releases.

## Vendor Documentation Crawl

- https://docs.omni.co/ — product docs (unstable API + model reference + embed)
- https://omni.co/pricing
- https://omni.co/blog — quarterly re-crawl
- https://docs.omni.co/docs/API — API overview
- https://docs.omni.co/docs/API/users
- https://docs.omni.co/docs/API/connections
- https://docs.omni.co/docs/API/documents
- https://docs.omni.co/docs/API/embed
- https://docs.omni.co/docs/model/system-activity — System Activity reference
- https://docs.omni.co/docs/integrations/dbt

## Best Practices (synthesized)

1. **Warehouse-side tagging is the cost source** — configure Omni to tag queries (`application_name` / query comment with `document_id`) so Snowflake `QUERY_HISTORY.QUERY_TAG` or BigQuery `labels` pins cost to the Omni document.
2. **Free viewer = no direct cost, but warehouse cost per view** — don't ignore viewers just because they're free seats.
3. **Per-document view × avg-query-cost** gives a usable "$ per dashboard" approximation without System Activity access.
4. **Idle content**: documents with `updatedAt > 90d` and `views_last_30d == 0` = archive candidates.
5. **AI (Blobby) queries**: separate bucket — they can silently run expensive warehouse scans.
6. **Git workflow adoption**: track `model_commits` — teams using the Git workflow tend to be healthier adopters.
7. **Role hygiene**: paid seats who never query in 60 days = downgrade-to-viewer candidates (since viewers are free).
8. **Connection audit**: multiple connections to the same warehouse should be rare; often indicates accidental prod/dev splits.
9. **Embed-on-SaaS customers**: track embed MAU separately from internal MAU.

## Costly's Current Connector Status

File: `backend/app/services/connectors/omni_connector.py`

**What it does today:**

- Auth: `Authorization: Bearer <api_key>`.
- `test_connection`: `GET /api/v0/connections`.
- `fetch_costs(days)`:
  - `GET /api/v0/users` → user count.
  - `GET /api/v0/queries?created_after=...&limit=1000` → daily query stats.
  - Flat `$50/user/month / 30` daily cost, one row per day with the day's query count.
- Emits one `UnifiedCost` per day — `service="omni"`, `category=serving`.

**What it does well:** simple, resilient (swallows exceptions and returns `[]`), bearer auth right, date-range filter correctly formatted.

**What's broken / thin:**

1. **`/api/v0/*` is stale path** — current docs use `/api/unstable/`. Likely to 404.
2. **`/api/v0/queries` is not a real endpoint** — per-query history is not exposed via public REST. This call will always return empty on current tenants.
3. **Flat $50/user** ignores free Viewers. Free viewers shouldn't incur Costly-calculated cost.
4. **No role / tier classification** — admin/member/viewer mix not considered.
5. **No per-document, per-connection, or per-user breakdown** — all cost collapsed to platform-level.
6. **No warehouse-side query-tag join** — the single biggest missed opportunity.
7. **No embedded-session accounting.**
8. **Session-level detail absent** — `sessions` and `dashboard_views` untouched.
9. **AI / Blobby usage not captured.**
10. **Audit-log webhook ingestion not supported.**
11. **No pagination** on `/users` (ok for small tenants, breaks on larger).
12. **Generic exception swallow** — masks 404s and auth failures; need at least a log.

## Gaps

- **Switch API base** from `/api/v0/` to `/api/unstable/` (configurable; keep `v0` fallback for edge cases).
- **Remove `/queries` dependency** until a real endpoint exists; replace with either audit-log export or warehouse-tag join.
- **Role-based pricing**: classify users, treat Viewer as $0, paid tiers at per-seat rate with override.
- **Per-connection**: emit a `(connection_id, connection_name, dialect)` dimension on each row so the warehouse connector can join.
- **Per-document views** via `dashboard_views` (System Activity) when available; otherwise fallback to `documents.updatedAt`.
- **Warehouse query-tag join**: instruct customers to set Omni's `application_name`/query-tag and surface a dashboard reading from `QUERY_HISTORY.QUERY_TAG`.
- **Embed MAU** — if `embed/tenants` is enumerable, surface embedded seat count separately.
- **AI usage** — once exposed, bucket separately.
- **Audit-log webhook** — for enterprise customers, provide a receiver and ingest events.
- **Error logging** — log specific HTTP error codes and bodies to distinguish auth errors from missing endpoints.

## Roadmap

**P0 — Correctness**

- Move base path to `/api/unstable/`.
- Delete `/api/v0/queries` path; surface a warning in connector logs if requested.
- Log HTTP errors instead of swallowing.

**P1 — Tier + warehouse join**

- Role-based seat pricing with override (Viewer $0).
- Emit per-connection cost rows.
- Provide Snowflake/BigQuery integration guide: set Omni query tag → Costly auto-joins.

**P2 — Deeper usage**

- Per-document views via System Activity (where customer can export to warehouse).
- Embed tenant/MAU support.
- Audit-log webhook ingestion (enterprise).

**P3 — Parity + features**

- Blobby AI usage tracking when API lands.
- Git-commit cadence as a health metric.
- Idle-document report.
- Move to `omni-cli` when public.

## Change Log

- 2026-04-24: Initial knowledge-base created.
