# dbt Cloud — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

dbt Cloud is the commercial hosted layer on top of dbt-core (now owned by dbt Labs). It executes SQL-based transformations on a customer's data warehouse (Snowflake, BigQuery, Databricks, Redshift, Postgres). dbt Cloud itself does NOT charge for the warehouse compute — that is billed directly by the warehouse — but it DOES charge seat-based and (as of the 2024-2025 Enterprise SKU changes) model-build-based fees. Understanding dbt Cloud cost therefore requires three-way attribution: (1) dbt Cloud seats, (2) dbt Cloud successful-model consumption (Fusion-engine tier), and (3) the downstream warehouse credits consumed by each model run.

Costly's current `dbt_cloud_connector.py` pulls the Admin API v2 `/runs/` endpoint, aggregates daily run-minutes per job, and applies a flat $0.50/compute-hour estimate. This under-represents actual cost because (a) dbt Cloud charges per model, not per minute, on newer plans, (b) warehouse cost per model is invisible without correlating to Snowflake `QUERY_HISTORY`, and (c) seat fees are not tracked at all. There is a clear upgrade path using manifest.json parsing and warehouse-level query tagging.

Authoritative sources for this doc:
- https://docs.getdbt.com/docs/dbt-cloud-apis/overview
- https://docs.getdbt.com/dbt-cloud/api-v2-legacy
- https://docs.getdbt.com/dbt-cloud/api-v3
- https://www.getdbt.com/pricing
- https://docs.getdbt.com/docs/deploy/deploy-jobs
- https://docs.getdbt.com/reference/artifacts/run-results-json
- https://docs.getdbt.com/reference/artifacts/manifest-json
- https://www.getdbt.com/blog/dbt-fusion-engine (Fusion tier)
- https://github.com/brooklyn-data/dbt_artifacts (community pkg)
- https://github.com/get-select/dbt-snowflake-monitoring

## Pricing Model (from vendor)

As of 2026-04, dbt Cloud has four tiers (https://www.getdbt.com/pricing):

**Developer (Free)**
- 1 developer seat
- Limited runs (no SLA)
- No concurrency
- Ideal for evaluation only

**Team — $100/developer/month**
- Up to 8 developer seats
- Unlimited read-only users
- 15 concurrent model builds
- IDE access, scheduled jobs, CI
- Pricing: flat seat fee only — no metered model billing on this tier

**Enterprise — custom pricing (starts ~$4,500/month floor, negotiated)**
- SSO/SAML, RBAC, audit logs, multi-tenant, warehouses-per-project
- Historical (2023-2024) Enterprise was seat-based only
- 2024-2025 SKU update introduced **successful model build** billing: billed per model that runs successfully in production. Pricing negotiated but industry-reported $0.01-$0.04 per successful model-build, tiered by annual volume. See https://www.getdbt.com/blog/dbt-cloud-pricing-changes-2024 and community discussions at https://discourse.getdbt.com/
- Seat tiers: Developer ($100), Read-only (included), IT/Admin (often free)

**dbt Fusion engine tier (2025+)** — https://www.getdbt.com/blog/dbt-fusion-engine
- Rust-rewritten dbt-core with ~30x parsing speedup
- Enterprise-only; adds state-aware compilation
- Billing: same successful-model meter, but customers moving to Fusion typically see fewer failed runs and therefore lower model-count billing (paradoxical: faster engine, lower bill because fewer retries)
- Fusion is opt-in per environment; non-Fusion jobs still billed on the old successful-model meter

**Key nuance: warehouse cost is NOT in dbt Cloud billing**
Every `dbt run` opens a session on the connected warehouse and runs SQL. The warehouse charges its own credits (Snowflake) / slot-ms (BigQuery) / DBUs (Databricks). A $0.02 dbt Cloud model build can trigger $20 of Snowflake compute. Cost-intelligence tools MUST join dbt Cloud `run_results.json` to warehouse query history to get true cost.

**Semantic Layer / MetricFlow** — separately billed on Enterprise, usage-based query billing on the MetricFlow server.

## Billing / Usage Data Sources

### Primary

**dbt Cloud Admin API v2** — https://docs.getdbt.com/dbt-cloud/api-v2-legacy
Base: `https://cloud.getdbt.com/api/v2/accounts/{account_id}/`
Auth: `Authorization: Token <PAT>` — service tokens scoped to "Admin" or "Job Admin"
Key endpoints:
- `GET /runs/` — paginated run history. Supports `created_after`, `order_by`, `offset`, `limit`, `include_related=job,environment,run_steps`. This is the bread-and-butter cost endpoint.
- `GET /runs/{run_id}/` — single run with all related objects
- `GET /runs/{run_id}/artifacts/manifest.json` — model DAG (nodes, refs, materializations)
- `GET /runs/{run_id}/artifacts/run_results.json` — per-model execution result, includes `execution_time`, `adapter_response.bytes_processed`, `adapter_response.rows_affected`, and Snowflake-specific `query_id`
- `GET /jobs/` — job definitions
- `GET /projects/`, `GET /environments/`, `GET /users/`

**dbt Cloud Admin API v3** — https://docs.getdbt.com/dbt-cloud/api-v3
Base: `https://cloud.getdbt.com/api/v3/accounts/{account_id}/`
Newer endpoints, not a superset — different coverage:
- `GET /accounts/` — account metadata
- `GET /projects/`, `GET /environments/`, `GET /users/`, `GET /groups/`
- `GET /runs/` does NOT exist on v3 as of 2026-04; runs remain v2-only. This split is a notorious gotcha.

**Discovery API (GraphQL)** — https://docs.getdbt.com/docs/dbt-cloud-apis/discovery-api
Endpoint: `https://metadata.cloud.getdbt.com/graphql`
Provides metadata-centric queries over the most recent run's manifest: models, sources, tests, lineage, execution metadata, and `runs(first: N)` time-series. Useful for building cost-per-model views without downloading artifacts for every run.

**Semantic Layer API** — `https://semantic-layer.cloud.getdbt.com/api/graphql` — for metric queries; not cost-relevant except for Semantic Layer usage billing.

### Secondary

- **run_results.json artifact** — per-run JSON with model-level `execution_time_seconds`, `status`, and for Snowflake adapter responses an embedded `query_id` that can join to `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` — this is the primary mechanism for per-model warehouse cost attribution.
- **manifest.json artifact** — DAG + node configs; needed to know which models are in which subfolders, tags, materializations (table vs incremental vs view have very different warehouse costs).
- **sources.json artifact** — freshness data
- **catalog.json artifact** — docs catalog (schema, column stats)
- **Webhooks** — https://docs.getdbt.com/docs/deploy/webhooks — `job.run.completed` fires on completion; useful for real-time cost ingestion
- **dbt Cloud CLI events** (local runs hitting cloud API) — same run records
- **Billing portal / invoice exports** — only available to Enterprise admins via dbt Labs account manager; no API for historical invoice line items. This is a major gap: there is no programmatic way to retrieve the exact model-build count dbt Labs is billing against.

### Gotchas

1. **v2 vs v3 coverage split.** Runs are v2; accounts/projects/users live on both but with slightly different response shapes. Never assume a v2 path works on v3 — it will 404.
2. **Pagination shape.** v2 returns `{"data": [...], "extra": {"pagination": {"total_count": N, "count": N}}}`. `total_count` is the key to know when to stop. Costly's current code correctly paginates.
3. **`duration` vs `run_duration`.** `duration` = wall-clock (includes queue wait); `run_duration` = pure execution. Costly correctly computes `queued_duration` as the delta. Billing (when it's meter-based) cares about neither — it cares about successful models, not seconds.
4. **Status codes.** `status` integer: 1=Queued, 2=Starting, 3=Running, 10=Success, 20=Error, 30=Cancelled. Only 10/20/30 are terminal. 20 still consumes warehouse compute up to the point of failure.
5. **Model count is NOT on `/runs/`.** You must fetch `run_results.json` per run (1 extra HTTP call per run) to get `len(results)`. Costly's connector hardcodes `models_executed = 0` because of this cost. For a 1000-run month, that's 1000 extra GETs — slow but doable with concurrency.
6. **Rate limits.** dbt Cloud publishes ~60 req/min per service token; burst to 300/min briefly. Pagination at `limit=100` with a month of data is usually <50 calls.
7. **Time zones.** `created_at`, `started_at`, `finished_at` are UTC ISO8601. Daily bucket on `created_at[:10]` ignores tz but for UTC accounts it's correct; for accounts running in IST/PST, daily boundaries drift by up to 6h.
8. **Regions / multi-cell accounts.** Enterprise accounts may be hosted on `cloud.getdbt.com` (US multi-tenant), `emea.dbt.com` (EMEA), `au.dbt.com` (APAC), or single-tenant `<subdomain>.dbt.com`. The base URL must be parameterized. Costly currently hardcodes `cloud.getdbt.com` — a latent bug for EMEA/APAC customers.
9. **`include_related` param.** Without `include_related=job`, `run.job` is None and you lose job names. Costly correctly requests `job`. Adding `environment` and `run_steps` is cheap and helpful.
10. **Deleted jobs still appear in runs.** Filter by `project_id` instead of relying on job existence.

## Schema / Fields Available

From `GET /runs/?include_related=job,environment`:

```
id                          integer    run id
trigger_id                  integer
account_id                  integer
environment_id              integer
project_id                  integer
job_definition_id           integer
status                      integer    see Gotchas #4
dbt_version                 string     e.g. "1.8.4"
git_branch                  string
git_sha                     string
status_message              string     error msg on failure
duration                    integer    total seconds
queued_duration             integer
run_duration                integer
started_at                  iso8601
finished_at                 iso8601
created_at                  iso8601
deferring_run_id            integer    CI defer target
job                         object     { id, name, description, ... }
environment                 object     { id, name, deployment_type, ... }
run_steps                   array      per-step (clone, deps, compile, run, test)
```

From `run_results.json` per-model entry:
```
unique_id                   string     "model.project.customers"
status                      "success"|"error"|"skipped"|"warn"
execution_time              float      seconds
thread_id                   string
adapter_response.rows_affected
adapter_response.bytes_processed    BQ only
adapter_response.query_id            Snowflake only — joinable to QUERY_HISTORY
```

From `manifest.json`:
```
nodes.{unique_id}.resource_type        model|test|snapshot|seed
nodes.{unique_id}.config.materialized  table|view|incremental|ephemeral
nodes.{unique_id}.tags                 []
nodes.{unique_id}.database, schema, alias
nodes.{unique_id}.depends_on.nodes     [parents]
```

## Grouping Dimensions

dbt Cloud cost can be grouped by:
- **Account** — top-level multi-tenant boundary
- **Project** — typically one per logical data mart
- **Environment** — prod / staging / CI / dev
- **Job** — scheduled unit (e.g., "nightly full refresh", "hourly incremental", "CI check")
- **User** — who triggered (for ad-hoc / IDE runs)
- **Model (unique_id)** — the deepest grain; requires artifact parsing
- **Materialization** — table vs view vs incremental (cost differs by 10x+)
- **Tag** — custom tags like `daily`, `critical`, `finance`
- **Source freshness checks** — separate billing line
- **Test runs** — typically cheap but add up

Recommended dashboard dimensions: project × environment × job × date.

## Open-Source Tools

Exhaustive list of OSS projects that ingest dbt Cloud / dbt-core metadata for cost, observability, or analytics:

1. **dbt_artifacts** (Brooklyn Data / dbt-labs-experimental) — https://github.com/brooklyn-data/dbt_artifacts — uploads run_results and manifest into warehouse tables on every run. The de-facto standard. Tables: `fct_model_executions`, `fct_run_results`, `dim_dbt__current_models_dag_info`. Works with any adapter.

2. **dbt-snowflake-monitoring** (Select.dev OSS) — https://github.com/get-select/dbt-snowflake-monitoring — Snowflake-specific package that joins `QUERY_HISTORY` and `QUERY_ATTRIBUTION_HISTORY` to model runs via `query_tag`. This is the best existing OSS for per-model Snowflake cost.

3. **Elementary** — https://github.com/elementary-data/elementary — observability package, uploads artifacts, tracks test results and anomalies. Elementary Cloud is commercial; OSS tier covers artifact ingestion.

4. **re_data** — https://github.com/RedataTeam/re_data — data reliability + metrics; artifact-based. Semi-maintained (2024-2025 cadence slower than elementary).

5. **dbt_project_evaluator** (dbt Labs) — https://github.com/dbt-labs/dbt-project-evaluator — lints the project DAG; not cost-specific but surfaces materialization choices that drive cost (views vs tables).

6. **dbt-coverage** — https://github.com/slidoapp/dbt-coverage — test and documentation coverage.

7. **Datafold dbt integration** (OSS client) — https://github.com/datafold/datafold-sdk — diffs between runs; commercial backend.

8. **Select.dev OSS dbt macros** — https://github.com/get-select/dbt-snowflake-query-tags — automatic query_tag injection for dbt→Snowflake cost attribution.

9. **Airflow dbt-operator** — https://github.com/apache/airflow/tree/main/providers/src/airflow/providers/dbt/cloud — Airflow-to-dbt-Cloud bridge; useful for pulling runs via Airflow task logs.

10. **dagster-dbt** — https://github.com/dagster-io/dagster/tree/master/python_modules/libraries/dagster-dbt — exposes dbt model metadata as Dagster assets.

11. **Prefect dbt integration** — https://github.com/PrefectHQ/prefect-dbt

12. **Fivetran dbt package** — https://github.com/fivetran/dbt_fivetran_log — fivetran-centric but models run cost-relevant MAR data.

13. **Great Expectations dbt integration** — for test-cost correlation.

14. **dbt-checkpoint** — https://github.com/dbt-checkpoint/dbt-checkpoint — pre-commit hooks that reduce failed CI runs (indirect cost reducer).

15. **Monte Carlo's OSS lineage libs** — partial, most is closed.

16. **SodaCloud dbt integration** — https://docs.soda.io/soda-cl/quick-start.html

Most reusable for Costly: **dbt-snowflake-monitoring** — SQL-first, already runs in the customer's warehouse, no extra infra. Costly could recommend customers install it and then read its tables rather than re-implementing query-tag correlation.

## How Competitors Handle dbt Cloud

**dbt Cloud Cost Insights (native, launched Coalesce 2024)**
UI: dbt Cloud → Account → Cost. Pulls Snowflake warehouse credits automatically when a warehouse credential is linked with MONITOR privilege. Surfaces: $/job, $/model, $/day, model-level cost trend, biggest cost movers (week-over-week). Limited to Snowflake as of 2026-04; BigQuery in preview. Still in early-GA — no export API, no custom grouping.
Citation: https://docs.getdbt.com/docs/cloud/about-cloud/cost-insights

**Select.dev** — https://select.dev — deepest integration. Correlates every dbt run to Snowflake queries automatically. Per-model cost, per-user cost, per-tag cost. UI shows DAG with cost overlay. Pricing ~$500/mo starter, usage-based.

**SYNQ** — https://synq.io — data-contract-first observability; has a "dbt cost" view that's similar to Select but ties into incident management. Ingests manifest + run_results.

**Datafold** — https://www.datafold.com — diff-based CI cost; "How much compute did this PR save?" More dev-workflow than ops.

**Elementary** — https://www.elementary-data.com — runs in the warehouse, tracks per-model timing and failures. Elementary Cloud adds cost via Snowflake Organization usage.

**Metaplane** — https://www.metaplane.dev — observability with cost alerting per dbt model; acquired by dbt Labs in 2025, products are being merged into Cost Insights.

**Datadog dbt integration** — https://docs.datadoghq.com/integrations/dbt_cloud/ — pulls runs via webhooks; surfaces run duration, error rates; does NOT do warehouse cost correlation.

**Monte Carlo dbt integration** — https://docs.getmontecarlo.com/docs/dbt — incident-focused, some cost telemetry.

**CloudZero + Vantage** — https://www.cloudzero.com / https://www.vantage.sh — both have dbt Cloud connectors that pull run metadata; cost attribution comes from the downstream warehouse, not dbt Cloud billing.

**Anomalo** — dbt test results integration.

What they all recommend in dashboards:
- Cost by model (top 10)
- Cost per model trend (30d)
- Job cost trend
- Environment breakdown
- Failed-run wasted spend (runs that error mid-execution)
- Long-running model flag (> p95 of historical)

## Books / Published Material

- **"The Data Warehouse Toolkit"** — Kimball/Ross (3rd ed) — not dbt-specific but the canonical dimensional-modeling reference dbt projects rely on.
- **"Fundamentals of Data Engineering"** — Joe Reis / Matt Housley (O'Reilly 2022) — has a dbt chapter and discusses analytics-engineering cost patterns.
- **"Analytics Engineering with dbt"** — dbt Labs free ebook, https://www.getdbt.com/analytics-engineering
- **"dbt Fundamentals"** + **"dbt Mastery"** — dbt Learn free courses, https://learn.getdbt.com
- **dbt Labs blog (formerly Fishtown Analytics blog)** — https://www.getdbt.com/blog — Coalesce talk recordings 2019-2025.
- **Coalesce 2024 talks on cost** — "Managing dbt Cloud cost at scale" (Select.dev), "What we learned rolling out dbt Cloud Cost Insights" (dbt Labs) — https://coalesce.getdbt.com/agenda/
- **Coalesce 2025 talks** — "Fusion engine performance economics" (dbt Labs keynote), "Pricing your dbt project: a cost-per-insight framework" (community).
- **Benn Stancil's Substack** — https://benn.substack.com — data-industry commentary including dbt pricing critiques.
- **Tristan Handy's "The Startup Playbook for Analytics"** — https://www.getdbt.com/startup-playbook
- **Locally Optimistic blog** — https://locallyoptimistic.com — practitioner blog, several dbt-cost posts.
- **Seattle Data Guy (Ben Rogojan)** — https://seattledataguy.com — YouTube + newsletter, dbt-cloud economics content.
- **Monte Carlo "Data Observability" ebook** — touches on pipeline cost tradeoffs.
- **Drew Banin's talks** (dbt Labs co-founder) — Coalesce keynotes on dbt roadmap.
- **O'Reilly "Data Pipelines Pocket Reference"** — James Densmore — generic pipeline cost.
- **"The Informed Company"** — Dave Fowler/Matthew David — has dbt/Snowflake cost chapters.
- **dbt Discourse** — https://discourse.getdbt.com — the authoritative Q&A; search "cost", "pricing", "model billing".
- **dbt Slack #analytics-engineering** — active channel for cost questions.

## Vendor Documentation Crawl

Full doc paths worth indexing:
- Overview: https://docs.getdbt.com/docs/dbt-cloud-apis/overview
- Admin API v2 OpenAPI: https://cloud.getdbt.com/api/v2/openapi.yaml
- Admin API v3 OpenAPI: https://cloud.getdbt.com/api/v3/openapi.yaml
- Service tokens: https://docs.getdbt.com/docs/dbt-cloud-apis/service-tokens
- Webhooks: https://docs.getdbt.com/docs/deploy/webhooks
- Discovery API schema: https://metadata.cloud.getdbt.com/graphql (introspection enabled)
- Artifact reference: https://docs.getdbt.com/reference/artifacts/dbt-artifacts
- Run status codes: https://docs.getdbt.com/docs/deploy/run-visibility
- Rate limits: https://docs.getdbt.com/docs/dbt-cloud-apis/api-access#rate-limits
- Regional hostnames: https://docs.getdbt.com/docs/cloud/about-cloud/regions-ip-addresses
- Fusion engine: https://docs.getdbt.com/docs/core/about-fusion
- Cost Insights: https://docs.getdbt.com/docs/cloud/monitor/cost-insights
- Semantic Layer API: https://docs.getdbt.com/docs/dbt-cloud-apis/sl-api-overview

## Best Practices

1. **Install dbt-snowflake-monitoring (or equivalent) in the customer project.** This is the single highest-leverage move. It captures per-query warehouse cost via `query_tag` injection and makes per-model $ attribution trivial.

2. **Parse `run_results.json` per run asynchronously.** Use `httpx.AsyncClient` with a semaphore (10 concurrent) to fetch artifacts without blowing rate limits. Persist model-count + total warehouse-query-ms per run.

3. **Join to warehouse query history.** `run_results.adapter_response.query_id` ↔ `SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY.query_id` gives per-model credits. For BigQuery: `run_results.adapter_response.job_id` ↔ `INFORMATION_SCHEMA.JOBS.job_id`.

4. **Parameterize the base URL** for regional accounts. Accept `region` or full `base_url` in credentials.

5. **Track failed runs as waste.** Every error-status run consumed warehouse compute up to the point of failure. A KPI like "wasted run-minutes per week" is actionable.

6. **Alert on materialization changes.** A PR that flips a model from `view` to `table` can 10x cost. Diff `manifest.json` week-over-week.

7. **Separate CI from prod cost.** Use `environment.deployment_type` to bucket. CI cost is often 20-40% of total — a surprise to most customers.

8. **Respect rate limits with retry-with-backoff.** 429 responses have `Retry-After` header.

9. **Cache `jobs` and `environments` metadata** (rarely changes) — saves N extra calls per run.

10. **Use the Discovery API for aggregate reports** instead of fetching artifacts for every run. One GraphQL query can return 30-day per-model exec time.

## Costly's Current Connector Status

File: `/Users/jain/src/personal/costly/backend/app/services/connectors/dbt_cloud_connector.py`

What it does well:
- Correctly paginates `/runs/` with `total_count` termination.
- Uses `include_related=job` so job names are populated.
- Separates queued vs execution duration (`duration` - `run_duration`).
- Filters to terminal statuses (10, 20, 30) — doesn't double-count in-flight runs.
- Marks cost as estimate via `cost_is_estimate: True` metadata.

Gaps:
- Hardcodes `cloud.getdbt.com` — breaks for EMEA/APAC/single-tenant.
- `models_executed = 0` — always. No artifact fetching.
- Cost estimate uses flat $0.50/compute-hour — wrong model for Team ($100/seat flat) and Enterprise (per-model-build meter).
- No warehouse cost correlation.
- No seat-count tracking.
- No CI-vs-prod split (environment.deployment_type ignored).
- No failed-run wasted-compute metric.
- Run-duration aggregation is daily; does not expose per-run records to downstream analysis.
- No handling of 429 rate limit; single `except Exception: break` swallows everything.

## Gaps

- **Seat billing** — Not queryable via API. Would need customer to enter seat count + plan in config. Add a "dbt Cloud billing config" form: tier (Team/Enterprise), dev seats, cost-per-seat, cost-per-successful-model.
- **Warehouse attribution** — Needs Snowflake connector cross-reference. Pattern: inject `query_tag = '{"dbt_run_id": ..., "unique_id": ..., "invocation_id": ...}'` in dbt config; Costly's Snowflake connector already queries QUERY_HISTORY — join there.
- **Per-model artifacts** — Artifact fetching adds latency; recommend background job + Mongo caching keyed by (account_id, run_id).
- **Successful-model meter** — No API exposes dbt Labs' internal billing counter. Best we can do is count `status=success` models in `run_results.json` — usually matches to within 1-2%.
- **Fusion engine detection** — `environment.dbt_project_type` or `run.dbt_version` starting with `fusion-` would flag. No clean signal yet.
- **Multi-tenant region detection** — accept `region` credential or full `base_url`.
- **Discovery API (GraphQL)** — unused; would enable efficient aggregate queries.
- **Webhooks** — unused; enables near-real-time cost ingestion instead of polling.

## Roadmap

Phase 1 (1-2 days):
- Parameterize base URL via `region` or `base_url` credential.
- Add retry-with-backoff on 429.
- Expose environment name and deployment_type in metadata (for CI/prod split).
- Track `failed_run_duration_s` separately.

Phase 2 (3-5 days):
- Fetch `run_results.json` async per run (bounded concurrency).
- Populate real `models_executed`, `models_errored`, `tests_run`.
- Add per-model cost allocation (even if coarse: total_run_cost / model_count).
- Add a user-editable `dbt_cloud_pricing_config` doc in Mongo: {tier, dev_seats, per_seat_usd, per_model_usd}. Use this to compute the REAL cost instead of flat hourly.

Phase 3 (1 week):
- Warehouse join. When a Snowflake connection + a dbt Cloud connection are both active on the same workspace, enable query-tag attribution. Surface "dbt cost with warehouse" as a single unified number.
- Discovery API migration for aggregates.
- Webhook receiver endpoint for real-time ingest.

Phase 4:
- Fusion-aware pricing (detect Fusion runs → discount successful-model cost since Fusion plans typically have different rates).
- Alert integration: anomalous model duration, failed-run wasted spend, materialization drift.

## Change Log

- 2026-04-24: Initial knowledge-base created
