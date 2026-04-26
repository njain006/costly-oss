# Snowflake Lane — Backlog / In-Progress / Done

> Per-lane delivery log. Read in conjunction with [docs/connectors/snowflake.md](../connectors/snowflake.md) for the full KB.

## Done

### 2026-04-24 — AI_SERVICES_USAGE_HISTORY (April 2026 GA) + Cortex per-model pricing + freshness probe

Shipped end-to-end in a single pass:

1. **`_fetch_ai_services()`** — queries `SNOWFLAKE.ACCOUNT_USAGE.AI_SERVICES_USAGE_HISTORY` (new consolidated view covering Cortex Functions, Analyst, Search, Document AI, Universal Search). Emits per-model drill-down `UnifiedCost` records tagged `metadata.drilldown = True` so aggregators don't double-count against the billed-USD `AI_SERVICES` row in `USAGE_IN_CURRENCY_DAILY`.
2. **Four new `ai_inference` slugs** — `snowflake_cortex_analyst`, `snowflake_cortex_search`, `snowflake_document_ai`, `snowflake_universal_search`. Extends `SERVICE_TYPE_CATEGORY` + `SERVICE_TYPE_SLUG` maps.
3. **`AI_SERVICE_FAMILY_TO_TYPE`** alias table — handles the 12 possible `SERVICE_TYPE` values Snowflake's view may emit across accounts (e.g. `CORTEX` vs `CORTEX_FUNCTIONS`, `DOCUMENT_AI` vs `DOCUMENT_INTELLIGENCE`).
4. **`PricingConfig.cortex_model_prices`** — new pricing override dict, lowercased/normalized model keys. Invalid values silently ignored. Hooked into both defaults and custom overrides.
5. **`credit_price_for_cortex_model()`** resolver — three-level fallback: per-model override → per-service-type override → global credit price. Supports the real-world scenario where a customer pre-negotiates Llama-3 at $1.20/credit but pays $5/credit for Claude.
6. **`enable_ai_services_drilldown`** opt-out flag — customers can skip the query entirely if they don't want the extra API call (e.g. tiny accounts, privacy-sensitive setups).
7. **`_probe_freshness()`** — issues one `MAX(date_col)` query against the first readable source (`USAGE_IN_CURRENCY_DAILY` → `METERING_DAILY_HISTORY` → `WAREHOUSE_METERING_HISTORY`). Stores result in `self.freshness` for UI consumption; warns when lag exceeds 3h (the `WARN` threshold) or 24h (the `STALE` threshold) beyond the structural 24h daily cadence.
8. **Freshness opt-out** — when `prefer_org_usage=False`, the probe skips `ORGANIZATION_USAGE.*` views too so we never accidentally touch a view the user explicitly disabled.
9. **Structured permission errors** — missing grants on the new view emit `GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE <role>;`. Pre-April-2026 accounts that lack the view entirely get a softer "unavailable" warning so `fetch_costs()` keeps going.
10. **Tests** — 25 new cases, all green. Full suite: 80 Snowflake tests (was 55), 167 connector tests (was 142).
    - `TestAIServicesUsageHistory` — parametrized over 5 AI families × 12 function/model combinations.
    - `TestFreshnessProbe` — recent / lag / stale / denied / opt-out scenarios.
    - `TestPricingConfigCortexModels` — default/override/case/invalid-input handling.
11. **KB change log** updated in `docs/connectors/snowflake.md`.

**Grade delta: B+ → A-** (closed gaps #6, #9, #17; 14 gaps still outstanding).

## In Progress

_nothing_

## Backlog (ranked by customer impact)

1. **Query-level cost ingestion** — per-query `CREDITS_USED_CLOUD_SERVICES`, spill, scan, queue time from `QUERY_HISTORY`. The single biggest dimension missing. Blocks the "which query cost the most?" UI that Select.dev leads with.
2. **`WAREHOUSE_LOAD_HISTORY` right-sizing recommendations** — detect `AVG_RUNNING < 0.25 × cores_for_size` across 14 days → downsize candidate.
3. **Capacity-vs-on-demand auto-detection** — read `CONTRACT_ITEMS.CONTRACT_TYPE`; when CAPACITY, override `credit_price_usd` to the effective capacity rate automatically.
4. **`WAREHOUSE_EVENTS_HISTORY` auto-suspend tuning** — histogram of idle windows per warehouse; recommend tighter `AUTO_SUSPEND`.
5. **Gen-2 warehouse migration flag** — read `WAREHOUSES.RESOURCE_CONSTRAINT`; flag Gen-1 customers with est. savings.
6. **Region-aware default pricing** — derive from `CURRENT_REGION()` + edition lookup (AWS vs Azure vs GCP vs GovCloud).
7. **Iceberg request line breakdown** — today rolled under `snowflake_iceberg` via org_usage; want per-table surface.
8. **Snowpark Container Services unit economics** — node-type × hours, not just total credits.
9. **dbt-snowflake-monitoring package integration path** — nightly mart invocation option.
10. **Multi-account rollup** — iterate ORGADMIN accounts when Organization Account is configured.
11. **Budget + Resource Monitor read** — surface "at 85% of monthly budget" to dashboard.
12. **Write-back optimization actions** — `ALTER WAREHOUSE ... SET AUTO_SUSPEND/WAREHOUSE_SIZE` gated by human approval.
13. **Anomaly detection** via `CORTEX_FORECAST` on per-warehouse daily series.
14. **`ACCESS_HISTORY`** stale-table detection.

## References

- New view docs: https://docs.snowflake.com/en/sql-reference/account-usage/ai_services_usage_history (April 2026 GA)
- AI Budgets doc: https://docs.snowflake.com/en/user-guide/budgets
- ACCOUNT_USAGE latency table: https://docs.snowflake.com/en/sql-reference/account-usage#differences-between-account-usage-and-information-schema
