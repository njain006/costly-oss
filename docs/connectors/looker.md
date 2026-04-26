# Looker — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

Looker is Google Cloud's flagship BI platform; today it ships in two distinct products that are easy to confuse: **Looker (original / LookML)** — the enterprise governed semantic layer — and **Looker Studio** — Google's free, Data Studio-lineage self-serve tool. They have completely different pricing, APIs and cost-attribution surfaces. This knowledge base is for the **LookML Looker** because that is what the Costly `looker_connector.py` connects to. Pricing is **opaque, sales-led**: public sources converge on ~$3K/month platform floor + $60–$5,000/user/yr depending on seat tier (Viewer / Standard / Developer). Costly currently estimates cost by `user_count * $125/mo` which is a low-end proxy and should be replaced with real entitlement data. The canonical data source for usage is the **`system__activity` model**, queried via **Looker API 4.0 `/queries/run/{result_format}`** with an inline query spec. Dashboard/Explore/PDT/User granularity are all reachable, and Looker is unusually rich for cost attribution because PDTs run inside the warehouse (BigQuery / Snowflake / Redshift) and the `pdt_event_log.pdt_action_type` joins cleanly to warehouse-side cost. The primary gaps in Costly today: (a) real seat-tier cost, (b) per-dashboard/explore attribution, (c) PDT-to-warehouse-cost join, (d) embed usage, (e) orphan dashboard detection.

## Pricing Model

Looker does not publish SKU pricing. Publicly available data points (2024–2026):

- **Platform fee** floor on Google Cloud Marketplace: ~$3,000/month for a small Standard edition (up to 10 Standard users). Enterprise / Embed editions start higher, often $30K–$120K/yr+.
- **Editions**: Standard, Enterprise, Embed. Embed has a separate **metered usage** model (query/API call based) rather than per-seat.
- **Seats**:
  - **Viewer** — read-only dashboard access, ~$60/user/yr (historically called Viewer / Lite)
  - **Standard** — self-serve exploration, ~$60–$500/user/yr depending on contract
  - **Developer** — LookML authoring, ~$5,000/user/yr historically (now "Developer" under new GCP SKU). Typical ratio is ~1 Developer per 50–100 Standard users.
- **Looker Studio** (formerly Data Studio) — **free**; Studio Pro adds collaboration/SLA for ~$9/user/month.
- **Looker Embed** — metered: per query, per API call, or per monthly active user ("MAU") depending on deal.
- **GCP Integrated** — since 2023 some Looker capacity is billed through GCP consumption on the "Looker (Google Cloud core)" SKU on a CPU/hour basis.

Sources:

- https://cloud.google.com/looker/pricing — points to sales; no numbers
- https://cloud.google.com/looker/docs/admin-panel-general-pricing-overview
- https://cloud.google.com/marketplace/docs/understanding-looker-billing
- Third-party benchmarks: Vendr "Looker Pricing Benchmark" (2025); Hadrian "Looker pricing explained"; OMR reviews; Okta Workplace telemetry. All independently anchor ~$50K/yr median ACV for a mid-market Looker deployment.

**Opacity note:** Everything above is indicative. Any in-product cost estimate should be **overridable** by the customer with their actual contract numbers.

## Billing / Usage Data Sources

### Primary

- **`system__activity` LookML model** — Looker's own instrumented model available to users with the `see_system_activity` permission. Key explores:
  - `history` — every query run. Fields: `created_date`, `query_run_count`, `average_runtime`, `source`, `dashboard_id`, `dashboard_title`, `user_id`, `model`, `explore`, `result_source` (cache vs db), `slug`, `approximate_usage_in_bytes`.
  - `user` — user roster, roles, last-activity.
  - `dashboard` — dashboards, owners, `query_count`, `favorite_count`.
  - `dashboard_performance` — dashboard-level runtimes.
  - `pdt_event_log` — every PDT action (create / trigger / drop / check). Fields: `created_date`, `action`, `pdt_action_type`, `connection_name`, `table_name`, `runtime`.
  - `i__looker` — internal instance health. Scheduled job runs, API calls, asset counts.
  - `look` and `content_usage` — Look popularity and access counts.
  - `field_usage` — which LookML fields are actually queried (essential for dead-field pruning).
  - `scheduled_plan` — scheduled delivery jobs (email / Slack / webhook) and `scheduled_job` for runs.
- **API 4.0 `POST /queries/run/{result_format}`** — inline query spec (what Costly uses today). The body is a Query object: `{model, view, fields[], filters{}, sorts[], limit, query_timezone}`.
- **API 4.0 `GET /users`** — user roster; filter `is_disabled=false` for active headcount.

### Secondary

- **Admin Panel > System Activity dashboards** — prebuilt dashboards backed by the same explores; useful to mirror.
- **Admin Panel > Performance > Health Dashboard** — runtime, cache-hit, query-per-minute charts.
- **Admin Panel > Usage** — daily / weekly query volume.
- **Instance Audit Logs** — `audit_logs` explore; every admin action (user add/remove, role change, content share).
- **`event` and `event_attribute` explores** — lower-level per-event stream for SIEM-style analysis.
- **Scheduled Plan Endpoints** — `GET /scheduled_plans` to enumerate scheduled deliveries (big hidden cost driver).
- **Content Usage API** — `GET /content_usage` to get views-per-dashboard / views-per-Look over time.
- **Looker BigQuery export (Enterprise feature)** — some Enterprise plans export usage data daily to a customer-owned BigQuery dataset; where available this is the most efficient source.
- **Cloud Billing export (for Looker on GCP core SKU)** — `Cloud Billing BigQuery export` for the `Looker (Google Cloud core)` SKU.

### Gotchas

- **Auth flow**: `POST /api/4.0/login` returns `{access_token, token_type:"Bearer", expires_in:3600}`. The token expires in 1 hour and must be refreshed. Costly's current `LookerConnector._get_token` memoizes forever — **bug**: a long-running process will 401 after an hour. Fix: track `expires_in` and refresh, or simply `/login` per `fetch_costs()` call.
- **Header format**: Looker accepts both `Authorization: token <t>` and `Authorization: Bearer <t>`. `token` is the older style; Google's newer docs recommend `Bearer`. Costly currently uses `token` — still works.
- **Permission**: the querying user/service account needs `see_system_activity` to read `system__activity`. A plain "API-only" user will get 403 — make this explicit in the onboarding docs.
- **Inline query serialization**: `filters` values are strings in Looker filter syntax (e.g. `"after 2026-03-01"`, `"30 days"`, `"NOT NULL"`). Getting this wrong silently returns empty rows, not an error.
- **Pagination on `/queries/run/json`**: `limit` caps rows; for high-volume history you need date-bucketed queries or use the **paginated queries API** (`run_inline_query` with `limit` + `offset`).
- **Date vs datetime fields**: `history.created_date` buckets by UTC midnight of the instance's `query_timezone`. If the instance timezone is not UTC the daily roll-up will not line up with Costly's UTC buckets. Always pass `query_timezone: "UTC"` in the query body.
- **`pdt_event_log.action` values**: `create`, `drop`, `trigger`, `check`. Costly currently filters `action=create`, which undercounts cost because most of the compute comes from rebuilds (`trigger`).
- **Rate limits**: no published hard limit, but the instance can be back-pressured. Use a single worker and obey `429`.
- **Studio vs Looker conflation**: Looker Studio (free) has **no REST API for usage** — if a customer asks to connect "Looker" but means Studio, the connector cannot help. Validate by checking the URL (looker.com / cloud.google.com/looker vs datastudio.google.com / lookerstudio.google.com).

## Schema / Fields Available

Key `system__activity` fields for Costly:

| Explore | Field | Use |
|---|---|---|
| history | `created_date`, `created_time` | Time bucket |
| history | `query_run_count` | Query volume |
| history | `average_runtime`, `approximate_usage_in_bytes` | Cost proxies |
| history | `source` | UI / API / scheduled / embed — split cost by channel |
| history | `result_source` | `cache` vs `query` — cache-hit ratio |
| history | `dashboard_id`, `dashboard_title` | Per-dashboard grouping |
| history | `user_id`, `user.email` | Per-user grouping |
| history | `model`, `explore` | Per-model/explore grouping |
| history | `connection_name` | Which warehouse — join to BQ/SF cost |
| history | `slug`, `query.id` | Deduplicate, find expensive queries |
| dashboard | `id`, `title`, `favorite_count`, `query_count` | Orphan detection |
| content_usage | `last_accessed_date`, `view_count` | Find dead Looks / dashboards |
| pdt_event_log | `action`, `pdt_action_type`, `connection_name`, `table_name`, `runtime` | PDT cost attribution |
| field_usage | `model`, `view`, `field`, `times_used` | Dead field pruning |
| scheduled_plan | `id`, `name`, `cron`, `run_as_recipient`, `enabled` | Scheduled delivery cost |
| user | `id`, `email`, `is_disabled`, `models_dir_validation_version` | Active seat count |

## Grouping Dimensions

Cost and usage should be sliceable by:

- **Per-dashboard** — `dashboard_id` / `dashboard_title`. Essential for "which dashboards cost the most"?
- **Per-Look** — `look_id` / `look_title`.
- **Per-Explore** — `model` + `explore`. Surfaces expensive semantic-layer patterns.
- **Per-User** — `user_id` / `user.email` + seat tier.
- **Per-Model** — `model`. Aligns with product teams.
- **Per-Connection** — `connection_name`. **Critical** — lets us join to the warehouse's own cost view.
- **Per-PDT** — `pdt_event_log.table_name`.
- **Per-Source** — `history.source` (ui, api, scheduled_task, scheduler_internal, scheduler_api, embed).
- **Per-Site / Per-Instance** — for multi-instance customers.
- **Per-Schedule** — `scheduled_plan.id`.

## Open-Source Tools

- **[looker-open-source/sdk-codegen](https://github.com/looker-open-source/sdk-codegen)** — official codegen + Python, TS, Go, Swift, Kotlin, R SDKs. Apache-2.0. Active. Generate a typed SDK from the Swagger/OpenAPI spec — preferable to hand-rolled `httpx` calls.
- **[looker-open-source/looker_sdk](https://pypi.org/project/looker-sdk/)** — Python SDK published from the above. Installable via `pip install looker-sdk`.
- **[looker-open-source/gzr](https://github.com/looker-open-source/gzr)** — Ruby CLI for Looker admin (content migration, permissions dump). Useful for entitlement snapshots.
- **[looker-open-source/looker-datatools](https://github.com/looker-open-source/henry)** ("Henry") — CLI that runs health checks on LookML: unused fields, unused Explores, bloated models. Direct precursor to an "orphan dashboard" feature.
- **[spectacles-ci/spectacles](https://github.com/spectacles-ci/spectacles)** — LookML CI tool; content/assert/sql validators. Apache-2.0. ~600 stars.
- **[looker-open-source/lookerbot](https://github.com/looker-open-source/lookerbot)** — Slack bot (no longer maintained but reference for embed/slack patterns).
- **[joshtemple/lkml](https://github.com/joshtemple/lkml)** — LookML parser/serializer in Python. MIT. Useful for static analysis (find fields referenced in LookML vs actually queried).
- **dbt + exposures** — `dbt-artifacts` and `dbt_project_evaluator` track dbt→warehouse usage; exposures can include Looker Looks/dashboards to complete the lineage chain.
- **Catalog tools**: [DataHub](https://github.com/datahub-project/datahub) (Apache-2.0), [Amundsen](https://github.com/amundsen-io/amundsen), [Secoda](https://www.secoda.co/), [Castor](https://www.castordoc.com/) — all have Looker ingesters that crawl `system__activity` and LookML.
- **[godatadriven/dbt-looker](https://github.com/godatadriven/dbt-looker)** — generate LookML views from dbt models. Useful for lineage.
- **[pennfrugalfood/looker-rm](https://github.com/pennfrugalfood/looker-rm)** — community script to mass-remove stale content.

## How Competitors Handle Looker

- **CloudZero** — ships a Looker "kit": Looker block + a dbt package that joins `history` to warehouse cost via `connection_name`. Surface dashboards are: Cost per Dashboard, Cost per User, Cost per PDT, Idle PDT detector. https://www.cloudzero.com/blog/looker-cost/
- **Google Cloud's own Looker reports** — Admin Panel > Usage plus the System Activity dashboards. Benchmark for what "in-product" looks like; Costly should at minimum match these for breadth.
- **Vantage** — has a "Looker" integration that reads Cloud Billing export for the Looker SKU plus the Admin API for seat counts. https://www.vantage.sh/integrations
- **Select Star / Atlan / Metaplane / Castor** — catalog tools that ingest System Activity for **lineage and popularity**, not cost. Still useful to copy their orphan-detection heuristics (no views in last 90 days = candidate to archive).
- **ThoughtSpot** and **Sigma** — competing BI products ship their own "usage analytics" in-product; both claim Looker-parity for orphan / expensive-query detection.
- **The Information Lab / Pulse Analytics** — consultancies publish how-to audits for Looker: per-seat cost, per-query cost, per-PDT cost, scheduled-delivery cost. Pattern is uniform: `history * price_per_run_estimate + license_per_seat`.
- **Unravel / Bluesky** — warehouse-cost-optimization products that reach "up" into Looker PDTs via `connection_name` join.
- **Monte Carlo / Bigeye** — data-quality products that hook into `history` for "queries run on broken tables" alerting, not cost.

Dimensions every competitor tracks: seat count by tier, per-dashboard views, per-dashboard runtime, per-Explore query volume, cache-hit rate, scheduled-plan cost, PDT cost, embed cost, API-cost.

## Books / Published Material

- **"Looker 101 / Looker 201"** — self-paced training, originally Looker U, now free on cloud.google.com/looker/docs/training.
- **"LookML for Developers"** — Google Cloud Skills Boost / Coursera course.
- **"Data Modeling with LookML"** (Lloyd Tabb, various conference talks; foundational reading).
- **"The Definitive Guide to Looker"** — community-maintained Gitbook.
- **Looker Community: community.looker.com** — the most useful "book" is actually the community; search for "System Activity" / "usage analytics".
- **"Building a Scalable Data Warehouse with Data Vault 2.0"** (Linstedt, Olschimke) — warehouse modeling book frequently cited by Looker teams.
- **"Agile Data Warehouse Design"** (Corr, Stagnitto) — dimensional modeling underpinning LookML.
- **"Storytelling with Data"** (Knaflic) — cross-BI, mandatory reading for dashboard reviewers.
- **"The Big Book of Dashboards"** (Wexler, Shaffer, Cotgreave, O'Reilly) — cross-BI, includes Looker examples.
- **Looker blog on cloud.google.com/blog/products/data-analytics/** — search "LookML" / "cost".
- **dbt Coalesce 2023/2024/2025 sessions** — several talks on "dbt + Looker cost attribution" (Tristan Handy, Jeremy Cohen).
- **Podcasts** — Analytics Engineering Podcast (Tristan Handy), Catalog & Cocktails (Tim Gasper), Data Engineering Podcast (Tobias Macey) — search "Looker".

## Vendor Documentation Crawl

High-signal pages to re-crawl quarterly:

- https://cloud.google.com/looker/docs/admin-panel-users-system-activity — official System Activity explorer list
- https://cloud.google.com/looker/docs/reference/api — API reference (4.0)
- https://developers.looker.com/api/explorer — interactive explorer
- https://cloud.google.com/looker/docs/reference/param-explore — LookML reference
- https://cloud.google.com/looker/docs/best-practices/planning-pdts — PDT best practices
- https://cloud.google.com/looker/docs/dev-on-looker-scheduled-data-updates — scheduled jobs
- https://cloud.google.com/looker/docs/reference/api-and-integration/embed-api — Embed pricing/limits
- https://cloud.google.com/looker/docs/admin-panel-general-performance — performance dashboards
- https://cloud.google.com/looker/docs/release-notes — monthly release notes; watch for API or permissions changes
- https://discourse.looker.com/ — community discourse

## Best Practices (synthesized)

1. **Join Looker `history.connection_name` to warehouse cost** (BigQuery `INFORMATION_SCHEMA.JOBS_BY_PROJECT`, Snowflake `QUERY_HISTORY`, Redshift `SVL_QLOG`). This is the single biggest unlock — now every query has a dollar figure.
2. **Surface orphan dashboards** — dashboards with 0 views in last 90 days but still scheduled. Delete or unschedule.
3. **Flag expensive PDTs** — `pdt_event_log.runtime` top-N where the rebuild frequency is higher than the Explore's query frequency (PDT rebuilt more than used).
4. **Cache-hit rate target** — aim for >50% at the instance level; per-dashboard flag anything <20%.
5. **Scheduled-plan audit** — every plan should have an owner; disabled-user plans are a common landmine.
6. **Developer seats = scarce resource** — report Developer/Standard ratio; typical healthy is 1:50–1:100.
7. **Track Embed MAU separately** — embed contracts commonly bill per MAU; this should be a first-class metric.
8. **Respect governance** — `see_system_activity` is a privileged permission; the API user Costly uses should be dedicated ("costly-readonly") and scoped.
9. **Weekly digest** — per-team usage vs seat spend; this is what drives the "pay-for-your-BI" conversation internally.

## Costly's Current Connector Status

File: `backend/app/services/connectors/looker_connector.py`

**What it does today:**

- Auth: `POST /api/4.0/login` with `client_id`/`client_secret`, memoizes `access_token`.
- `test_connection`: `GET /api/4.0/user`.
- `fetch_costs(days)`: pulls (a) `history` daily query count, (b) `users` active count, (c) `pdt_event_log` daily create count.
- Cost model: `user_count * $125/month / 30` as daily base, distributed across days by query-volume share.
- Emits two kinds of `UnifiedCost`:
  - `service="looker"`, `category=serving` — proportional license cost per day.
  - `service="looker_pdt"`, `category=transformation` — `cost_usd=0` (compute is attributed to warehouse).

**What it does well:** correct API shape (4.0), correct explore/view names, sensible separation of license vs compute, graceful failure (returns `[]` on exception).

**What's broken / thin:**

1. Token TTL not respected — 1-hour expiry means long-running scheduler runs will 401.
2. Seat cost is one flat $125/user — ignores Viewer/Standard/Developer tiers.
3. `pdt_event_log` filter is `action=create` only; should include `trigger` (incremental rebuilds) and `check`.
4. No per-dashboard, per-model, per-connection breakdown.
5. No cache-hit or runtime fields pulled from `history`.
6. Daily query count limit is `days+1` — for >30 days history this will truncate.
7. No `scheduled_plan` ingestion; scheduled delivery is a blind spot.
8. `query_timezone` not forced to UTC — date buckets may slip.
9. `_get_user_count` just counts rows — no tier split, no disabled filter beyond the URL query (which is right) but no per-role weighting.
10. No retry / backoff on 429/5xx.
11. Bearer vs token header not a problem today but should align with GCP standard.

## Gaps

- **Seat tier**: add Admin API call to fetch roles / permission sets, classify each user into Viewer / Standard / Developer, price each tier independently. Let the customer override price per tier in settings.
- **Per-dashboard cost**: pull `history` grouped by `dashboard_id` and join to `content_usage` for view_count.
- **Per-connection / warehouse join**: emit a unified record per `(date, connection_name)` so the warehouse connector can join its own cost.
- **PDT cost attribution**: `pdt_event_log` runtime + connection_name, then pull warehouse cost for the same time window and attribute.
- **Scheduled delivery audit**: enumerate `scheduled_plan` + `scheduled_job` for the last 30 days; report volume and runtime.
- **Cache-hit telemetry**: `history.result_source` distribution per dashboard.
- **Orphan detection**: dashboards with zero views in N days.
- **Embed MAU**: separate from interactive MAU — requires `history.source in ('embed', 'api')`.
- **GCP Billing export**: when `looker_sku` line item exists in Cloud Billing, read it directly and replace the heuristic.
- **Multi-instance** support: one customer may have prod + dev Looker; today we assume one URL.
- **Auth refresh**: track `expires_in` and re-login.
- **Official SDK**: migrate off hand-rolled `httpx` to `looker_sdk` for type-safety and retry.

## Roadmap

**P0 — Correctness (next 1–2 weeks)**

- Fix token expiry in `_get_token`.
- Force `query_timezone: "UTC"` in every inline query.
- Raise `limit` or paginate for >30-day fetches.
- Broaden `pdt_event_log` filter to include `trigger`.

**P1 — Attribution (month 1)**

- Emit per-dashboard and per-connection granular `UnifiedCost` rows.
- Add `history.result_source` cache-hit metric.
- Add scheduled_plan enumeration.
- Seat-tier classification and per-tier pricing with overrides.

**P2 — Warehouse join (month 2)**

- Join on `connection_name` to Snowflake/BigQuery connectors to attribute warehouse cost back to Looker dashboards.
- Ship "Expensive Looker Dashboards" report.

**P3 — Advanced (month 3+)**

- Orphan-dashboard detector.
- Embed MAU analytics.
- Migrate to `looker_sdk` with tenacity-based retry.
- GCP Billing export ingestion for authoritative spend.
- Multi-instance support.

## Change Log

- 2026-04-24: Initial knowledge-base created.

## Re-recording contract fixtures

Contract tests for this connector live at `backend/tests/contract/test_looker.py`
and load JSON fixtures from `backend/tests/fixtures/looker/`. The fixtures are
intentionally hand-written from the public API docs so they don't leak any
real account data — every contributor can run the suite offline.

To capture fresh fixtures against a real Looker account when the API
schema drifts, set credentials and run pytest with `--record-mode=once`:

```bash
cd backend
LOOKER_CLIENT_ID=xxx LOOKER_CLIENT_SECRET=yyy LOOKER_INSTANCE_URL=https://your.looker.com \
    pytest tests/contract/test_looker.py --record-mode=once
```

Then sanitize the captured JSON (strip account ids, emails, tokens) before
committing. See `docs/testing/contract-tests.md` for the philosophy.


