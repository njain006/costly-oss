# Connector Ground Truth

> Single authoritative reference for every Costly connector. For each platform: canonical data source, field list, grouping dimensions, auth model, rate limits, and gotchas. Treat this file as the spec — if a connector diverges from what's below, either update the code or update this doc (with a dated note and link to the new vendor reference).
>
> Last reviewed: 2026-04-23. Connector files live under `backend/app/services/connectors/`.

---

## Anthropic (Admin API)

1. **Canonical data source** — `GET https://api.anthropic.com/v1/organizations/cost_report` for dollar cost and `GET https://api.anthropic.com/v1/organizations/usage_report/messages` for token breakdowns. `cost_report` is the invoice-authoritative source; `usage_report` is the only place tokens (including cache tiers) are exposed. Both require an **Admin API key** (not a regular API key).
2. **Secondary / fallback** — `GET /v1/models` only confirms the key is valid (no cost data). If the key lacks admin scope, return empty and prompt the user to generate an admin key. Do **not** fall back to `/v1/messages` pricing math — tokens can come from the client and Anthropic's pricing list is the source of truth.
3. **Fields returned** (from `usage_report/messages`): `starting_at`, `ending_at`, `workspace_id`, `api_key_id`, `model`, `service_tier` (`standard` / `priority` / `batch`), `context_window` (`"0-200k"` / `"200k-1M"`), `uncached_input_tokens`, `cache_creation.ephemeral_5m_input_tokens`, `cache_creation.ephemeral_1h_input_tokens`, `cache_read_input_tokens`, `output_tokens`, `server_tool_use.web_search_requests`. From `cost_report`: `starting_at`, `ending_at`, `workspace_id`, `description`, `cost_type`, `token_type`, `context_window`, `model`, `service_tier`, `amount.currency`, `amount.value`.
4. **Grouping dimensions** — `group_by[]=workspace_id`, `api_key_id`, `model`, `service_tier`, `context_window`, `cost_type`. Bucketed via `bucket_width=1d` / `1h`.
5. **Pricing tier / SKU taxonomy** — (model × service_tier × context_window × token_type). `token_type` is one of `uncached_input_tokens`, `cache_creation.ephemeral_5m_input_tokens`, `cache_creation.ephemeral_1h_input_tokens`, `cache_read_input_tokens`, `output_tokens`, `web_search_tool_requests`.
6. **Cache / discount / commitment modifiers** — Prompt cache reads at **10% of input list**, 5-min writes at **1.25× input**, 1-hour writes at **2.0× input**. `service_tier=batch` ⇒ **50% discount**. `service_tier=priority` ⇒ premium (committed throughput). Enterprise commitments surface via `cost_report` only (tokens themselves don't show the discount).
7. **Auth model** — Admin API key, header `x-api-key: sk-ant-admin01-...` + `anthropic-version: 2023-06-01`. Generate in console.anthropic.com → Organization Settings → Admin Keys. Regular `sk-ant-api03-...` keys return 403 on usage endpoints.
8. **Pagination + rate limits** — Cursor-based via `page` token in response. Rate limit: 50 req/min per admin key. `bucket_width=1h` can explode row count — prefer `1d` for >7-day windows.
9. **Gotchas** — (a) The old beta header `anthropic-beta: messages-batches-2024-09-24` is no longer required. (b) `cost_report` amounts are in the currency the org is billed in — check `amount.currency`, don't hardcode USD. (c) `usage_report` tokens for the current open UTC day are incomplete; wait until T+1 to reconcile. (d) Priority tier shows up as its own row even for the same model — don't deduplicate by `model` alone.
10. **Citations** — [Usage & Cost Admin API](https://docs.anthropic.com/en/api/admin-api/usage-cost), [Prompt caching pricing](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching), [Batch API](https://docs.anthropic.com/en/docs/build-with-claude/batch-processing), [Priority tier](https://docs.anthropic.com/en/api/service-tiers).

Code: `anthropic_connector.py`. Current implementation still uses the older `/v1/organizations/usage` path — upgrade to `usage_report/messages` + `cost_report` next.

---

## Claude Code (JSONL transcripts)

1. **Canonical data source** — `~/.claude/projects/<slugified-cwd>/<session-uuid>.jsonl`, one line per message. Assistant-role rows carry `message.usage` with token counts. This is the **only** way to attribute Claude Code Max/Pro subscription traffic — the Anthropic Admin API does not surface it because those messages don't pass through the customer's org key.
2. **Secondary / fallback** — None. If the user wants cross-machine aggregation, the project directory must be synced (e.g. shared network drive) or each machine runs its own connector instance.
3. **Fields returned** per assistant turn: `timestamp` (ISO-8601 Z), `sessionId` (uuid), `cwd`, `gitBranch`, `message.model`, `message.usage.input_tokens`, `message.usage.output_tokens`, `message.usage.cache_read_input_tokens`, `message.usage.cache_creation_input_tokens` (flat, legacy), `message.usage.cache_creation.ephemeral_5m_input_tokens`, `message.usage.cache_creation.ephemeral_1h_input_tokens`, `message.usage.service_tier`.
4. **Grouping dimensions** — `date` (UTC day), `project` (derived from `cwd`), `model`, `sessionId`, `gitBranch`. The current connector buckets by `(date, project, model)`.
5. **Pricing tier / SKU taxonomy** — Same as Anthropic Messages API (model × cache-tier × input/output). List-price table lives in `claude_code_connector.py:MODEL_PRICING`; cache multipliers are module-level constants.
6. **Cache / discount / commitment modifiers** — `cache_read` = 0.10 × input, `cache_write_5m` = 1.25 × input, `cache_write_1h` = 2.0 × input. No batch/priority in Claude Code. If the user is on a flat-fee subscription (Claude Code Max/Pro), the computed dollars are a **notional list-price value** not an invoice — surface this distinction in the UI as "imputed list-price cost" vs "invoice cost".
7. **Auth model** — Local filesystem read only. Credentials object accepts `projects_dir` override; default is `Path.home() / ".claude" / "projects"`. No network calls.
8. **Pagination + rate limits** — N/A. Use streamed line iteration so a 100-MB JSONL doesn't blow memory.
9. **Gotchas** — (a) Older Claude Code versions emit only flat `cache_creation_input_tokens` with no 5m/1h breakdown — treat as 5m. (b) Non-assistant rows (user, tool, system) have no `usage` — skip. (c) `cwd` was introduced mid-2025; older transcripts only have the slugified directory name (`-Users-jain-src-foo`), strip the leading dash. (d) JSON decode errors are common (partial writes during live sessions) — skip the line, don't abort the file. (e) Timestamps are in UTC but local files may contain mixed tz suffixes — always normalize via `datetime.fromisoformat(ts.replace("Z", "+00:00"))`.
10. **Citations** — [Claude Code docs](https://docs.anthropic.com/en/docs/claude-code), [Pricing — Claude Code](https://docs.anthropic.com/en/docs/claude-code/billing).

Code: `claude_code_connector.py` (reference implementation — `TokenUsage` dataclass is the canonical token-tier struct for the whole codebase).

---

## OpenAI (Usage API + Costs API)

1. **Canonical data source** — `GET https://api.openai.com/v1/organization/costs` for dollars (invoice-authoritative) and `GET https://api.openai.com/v1/organization/usage/{bucket}` for token/request counts. Both require an **Admin API key** (sk-admin-...). Bucket names you MUST query: `completions`, `embeddings`, `moderations`, `images`, `audio_speeches`, `audio_transcriptions`, `vector_stores`, `code_interpreter_sessions`. Missing any bucket means missing cost categories on the dashboard.
2. **Secondary / fallback** — The `/v1/organization/usage/completions` endpoint returns token counts without dollars; fall back to estimating cost from the model × token × list-price table if `/costs` returns empty or the key lacks cost scope. Legacy `/dashboard/billing/usage` is deprecated (EOL 2026-01-01, check console if still live).
3. **Fields returned** — `start_time` (unix), `end_time`, `results[].model`, `results[].input_tokens`, `results[].output_tokens`, `results[].input_cached_tokens`, `results[].input_audio_tokens`, `results[].output_audio_tokens`, `results[].num_model_requests`, `results[].project_id`, `results[].user_id`, `results[].api_key_id`, `results[].batch`. From `/costs`: `results[].amount.value`, `results[].amount.currency`, `results[].line_item` (e.g. `gpt-4.1-2025-04-14:input_cached`), `results[].project_id`.
4. **Grouping dimensions** — `group_by[]` accepts: `project_id`, `user_id`, `api_key_id`, `model`, `batch`, `line_item`. Bucketing via `bucket_width=1m` / `1h` / `1d`.
5. **Pricing tier / SKU taxonomy** — `{model}:{tier}` line items where tier is one of `input`, `input_cached`, `output`, `input_audio`, `output_audio`, `batch_input`, `batch_output`. Images: per-image by size+quality. Audio: per-minute (whisper) and per-token (4o audio). Vector stores: per-GB-day. Code interpreter: per-session.
6. **Cache / discount / commitment modifiers** — `input_cached` = **50% of input** (model-family dependent; check live pricing). Batch API = **50% discount**. Flex tier (o-series) = **~50% discount** on async jobs. Scale Tier = custom committed throughput, priced outside list and reflected in `/costs` only. Enterprise agreements show up as negative-value `credit` line items.
7. **Auth model** — `Authorization: Bearer sk-admin-...` and optional `OpenAI-Organization: org-...`. Admin keys are generated under Settings → Admin Keys (requires Owner role). Project-scoped keys work for `usage` but not `costs`.
8. **Pagination + rate limits** — Cursor via `next_page` in response; pass as `page=` on next call. Rate limit: 60 req/min per admin key. `bucket_width=1m` is expensive — use `1d` by default.
9. **Gotchas** — (a) `/organization/costs` returns values in **dollars**, not cents, as of the 2025-11 rollout — the legacy assumption `/100` is wrong for current production. Check `amount.currency` and use `amount.value` directly. (b) `moderations`, `images`, `audio_*`, `vector_stores`, `code_interpreter_sessions` buckets were split out in late 2025 — old connector code that only hits `completions` + `embeddings` under-reports by 10-30% for multimodal orgs. (c) `project_id` is only populated if the key being tracked is project-scoped; legacy user keys emit NULL. (d) Realtime API usage is reported under `audio_speeches` + `audio_transcriptions` split, not in `completions`. (e) Token counts on current UTC day are delayed 15-60 min.
10. **Citations** — [OpenAI Usage API](https://platform.openai.com/docs/api-reference/usage), [OpenAI Costs API](https://platform.openai.com/docs/api-reference/usage/costs), [Prompt caching pricing](https://platform.openai.com/docs/guides/prompt-caching), [Batch API](https://platform.openai.com/docs/guides/batch), [Flex processing](https://platform.openai.com/docs/guides/flex-processing).

Code: `openai_connector.py`. Upgrade path: add the 6 missing buckets and drop the `/100` division on `/costs`.

---

## Google Gemini / Vertex AI

1. **Canonical data source** — **BigQuery billing export**, table `<billing_project>.<dataset>.gcp_billing_export_resource_v1_<BILLING_ACCOUNT_ID>` (the `resource` variant includes per-resource labels — always prefer it over `gcp_billing_export_v1_*`). Filter `service.description IN ('Vertex AI API', 'Generative Language API')`. This is the invoice-authoritative source.
2. **Secondary / fallback** — Cloud Billing API `GET https://cloudbilling.googleapis.com/v1/services/{VERTEX_AI_SERVICE}/skus` for list-price, plus Cloud Monitoring metric `aiplatform.googleapis.com/publisher/online_serving/token_count` for near-real-time token counts when billing export is lagged (up to 36h). AI Studio API keys have **no** dollar reporting — only model-level token quotas via `generativelanguage.googleapis.com/models`.
3. **Fields returned** (BigQuery export): `billing_account_id`, `service.description`, `sku.id`, `sku.description` (e.g. "Gemini 2.0 Flash - Input Text"), `usage_start_time`, `usage_end_time`, `project.id`, `project.labels`, `resource.name`, `resource.global_name`, `location.region`, `cost`, `currency`, `currency_conversion_rate`, `usage.amount`, `usage.unit` (`token_count`, `character_count`, `1 ephemeral instance`), `credits[]` (committed-use, sustained-use, free-tier, promotional), `labels[]`, `system_labels[]`.
4. **Grouping dimensions** — `project.id`, `sku.description`, `resource.labels.model_id`, `location.region`, `labels.*` (user labels). For Vertex, group by `resource.name` to separate training jobs, online-prediction endpoints, and batch prediction.
5. **Pricing tier / SKU taxonomy** — (model × modality × tier). SKU strings carry the modality: `Gemini 2.0 Flash Input Text`, `Gemini 2.0 Flash Input Image`, `Gemini 2.0 Flash Output Text`, `Gemini 2.0 Flash Cached Input`, `Gemini 2.0 Flash Batch Input`, `Gemini 2.0 Flash Context Cache Storage`. Always split by SKU — do not collapse by model name.
6. **Cache / discount / commitment modifiers** — Context caching: reads ~25% of input; storage charged per hour of cache TTL. Batch mode = **50% discount**. Provisioned Throughput = committed-use — shows as its own SKU. CUDs / SUDs appear under `credits[]` as negative amounts. Enterprise Discount Program (EDP) shows as `EDP_CREDIT` in `credits[].name`.
7. **Auth model** — Service account JSON with `roles/bigquery.dataViewer` on the billing dataset AND `roles/bigquery.jobUser` on the billing project. For Cloud Billing API fallback: `roles/billing.viewer` on the billing account. AI Studio: plain `x-goog-api-key` header, no IAM.
8. **Pagination + rate limits** — BigQuery jobs have their own quotas (100 concurrent queries / project). Billing API: 300 req/min. AI Studio: 60 req/min per key.
9. **Gotchas** — (a) Billing export is delayed **up to 24h** after usage; never trust it for "today". (b) `currency_conversion_rate` is set — if you want all-USD, multiply `cost * currency_conversion_rate` only when `currency != 'USD'`. (c) `gcp_billing_export_standard_v1_*` lacks resource-level detail — always use `_resource_v1_`. (d) Vertex AI Pipelines emit SKUs under `Vertex AI Pipelines`, not `Vertex AI API` — widen the filter if you want full attribution. (e) Free-tier Gemini API quota emits `Free tier` in credits with cost=0 — don't filter those out, they count toward quota tracking.
10. **Citations** — [Cloud Billing BigQuery export schema](https://cloud.google.com/billing/docs/how-to/bq-examples), [Cloud Billing Catalog API](https://cloud.google.com/billing/docs/reference/catalog/rest/v1/services.skus), [Vertex AI pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing), [Context caching pricing](https://ai.google.dev/gemini-api/docs/caching).

Code: `gemini_connector.py` — currently estimates via token counts + list price; upgrade to BigQuery export when the user provides a billing dataset.

---

## AWS

1. **Canonical data source** — **Data Exports CUR 2.0 in FOCUS 1.0 format** (or FOCUS 1.2 when GA) to S3, queried via **Athena** on the auto-provisioned table. Table columns follow the FOCUS spec exactly — no AWS-idiosyncratic field names. This replaces legacy CUR 1.0 which is being deprecated.
2. **Secondary / fallback** — **Cost Explorer API** (`ce:GetCostAndUsage`) for orgs that haven't enabled CUR 2.0. CE is capped at 13 months of history and has a **$0.01 per API call** charge — use only for recent/interactive queries. Cost Optimization Hub (`cost-optimization-hub:ListRecommendations`) for savings recs. Never use deprecated `cur:DescribeReportDefinitions` with CUR 1.0.
3. **Fields returned** (FOCUS 1.0 columns): `BillingAccountId`, `SubAccountId`, `BillingPeriodStart`, `BillingPeriodEnd`, `ChargePeriodStart`, `ChargePeriodEnd`, `ServiceCategory`, `ServiceName`, `ProviderName`, `PublisherName`, `InvoiceIssuerName`, `ResourceId`, `ResourceName`, `ResourceType`, `Region`, `AvailabilityZone`, `SkuId`, `SkuPriceId`, `ListCost`, `ContractedCost`, `EffectiveCost`, `BilledCost`, `BillingCurrency`, `PricingCategory`, `PricingQuantity`, `PricingUnit`, `CommitmentDiscountId`, `CommitmentDiscountType`, `CommitmentDiscountCategory`, `CommitmentDiscountStatus`, `Tags` (map).
4. **Grouping dimensions** — Any FOCUS column. Most useful: `ServiceName`, `SubAccountId`, `Region`, `ResourceType`, `Tags['team']`, `Tags['cost_center']`, `CommitmentDiscountType`.
5. **Pricing tier / SKU taxonomy** — `SkuId` + `SkuPriceId` uniquely identify a SKU+rate. `PricingCategory` is one of `Standard`, `Committed`, `Dynamic`, `Other`. `PricingUnit` follows UCUM where applicable.
6. **Cache / discount / commitment modifiers** — Savings Plans + Reserved Instances show in `CommitmentDiscountType=SavingsPlan` / `Reservation` and split `ListCost` vs `EffectiveCost` vs `BilledCost`. EDP / Private Pricing Agreement discounts appear as the delta between `ListCost` and `ContractedCost`. Spot is a `PricingCategory=Dynamic`. Free tier appears as `ListCost > 0, BilledCost = 0`.
7. **Auth model** — IAM role (preferred — cross-account assume-role) or access key. Required permissions: `cur:DescribeReportDefinitions`, `athena:StartQueryExecution`, `athena:GetQueryResults`, `glue:GetTable`, `s3:GetObject` on the CUR bucket. For CE fallback: `ce:GetCostAndUsage`, `ce:GetDimensionValues`, `ce:GetTags`.
8. **Pagination + rate limits** — Athena: 20 concurrent queries per account by default (request increase). CE: 5 TPS. Data Exports: eventual consistency, new day drops ~10-12h after UTC midnight.
9. **Gotchas** — (a) CUR 1.0 has `lineItem/UsageAmount`-style slash-delimited column names that break SQL — FOCUS 1.x fixed this. Always choose FOCUS when creating a new export. (b) Athena charges $5/TB scanned — partition your CUR table by `BillingPeriodStart` and `SubAccountId` to avoid full scans. (c) `EffectiveCost` is the right column 95% of the time; `BilledCost` excludes credits and misses committed-use math. (d) Amortized RI/SP costs only appear when you enable "Include resource IDs" + FOCUS — legacy CUR 1.0 hid them. (e) CE `group_by` supports max 2 dimensions; use CUR for deeper slicing.
10. **Citations** — [FOCUS 1.0 spec](https://focus.finops.org/focus-specification/), [CUR 2.0 & FOCUS exports](https://docs.aws.amazon.com/cur/latest/userguide/table-dictionary-cur2.html), [Cost Explorer API](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_Operations_AWS_Cost_Explorer_Service.html), [Cost Optimization Hub](https://docs.aws.amazon.com/cost-management/latest/userguide/cost-optimization-hub.html).

Code: `aws_connector.py` — currently uses Cost Explorer only. Migrate to CUR/Athena for orgs with >$1K/mo spend.

---

## Snowflake

1. **Canonical data source** — `SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY` for dollar-cost attribution across accounts in an org. For single-account depth: `SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY` (credits), `SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY` (everything including serverless), `SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY` (per-query cost with `credits_attributed_compute`).
2. **Secondary / fallback** — `INFORMATION_SCHEMA.WAREHOUSE_METERING_HISTORY` for real-time (last 14 days) when ACCOUNT_USAGE lag is unacceptable. `ORGANIZATION_USAGE.CONTRACT_ITEMS` for contract pricing. Snowsight Cost Management UI exports CSV as last resort.
3. **Fields returned** (`USAGE_IN_CURRENCY_DAILY`): `ORGANIZATION_NAME`, `CONTRACT_NUMBER`, `ACCOUNT_NAME`, `ACCOUNT_LOCATOR`, `REGION`, `SERVICE_LEVEL`, `USAGE_DATE`, `USAGE_TYPE` (`compute`, `storage`, `data transfer`, `cloud services`, `serverless tasks`, `materialized views`, `snowpipe`, `snowpipe streaming`, `automatic clustering`, `search optimization`, `replication`, `query acceleration`, `cortex`, `ai services`, `budget`), `CURRENCY`, `USAGE`, `USAGE_UNITS`, `USAGE_IN_CURRENCY`, `BALANCE_SOURCE` (`capacity`, `rollover`, `free usage`, `overage`, `rebate`). From `QUERY_ATTRIBUTION_HISTORY`: `QUERY_ID`, `USER_NAME`, `WAREHOUSE_NAME`, `CREDITS_ATTRIBUTED_COMPUTE`, `CREDITS_USED_QUERY_ACCELERATION`, `PARENT_QUERY_ID`, `ROOT_QUERY_ID`.
4. **Grouping dimensions** — `ACCOUNT_NAME`, `USAGE_TYPE`, `SERVICE_LEVEL`, `WAREHOUSE_NAME`, `USER_NAME`, `DATABASE_NAME`, `QUERY_TAG`, `ROLE_NAME`.
5. **Pricing tier / SKU taxonomy** — (edition × region × `USAGE_TYPE`). Editions: Standard, Enterprise, Business Critical, VPS. Serverless features bill separately (`automatic clustering`, `search optimization`, `materialized views`, `snowpipe`, `cortex`). Storage billed at on-demand or upfront rate from `CONTRACT_ITEMS`.
6. **Cache / discount / commitment modifiers** — Capacity commitments show via `BALANCE_SOURCE='capacity'`. Overage via `BALANCE_SOURCE='overage'`. Rollover credits from prior contract periods. Query acceleration service is opt-in and billed separately. Warehouses with `SCALING_POLICY='ECONOMY'` queue more to save credits. `RESULT_CACHE` hits are free — check `QUERY_HISTORY.TOTAL_ELAPSED_TIME = 0 AND EXECUTION_STATUS='SUCCESS'` or `RESULT_SCAN`.
7. **Auth model** — Key-pair auth (preferred — Costly default). Role must have `USAGE` on `SNOWFLAKE.ACCOUNT_USAGE` and `SNOWFLAKE.ORGANIZATION_USAGE` schemas (typically `ACCOUNTADMIN` or a dedicated `COSTLY_ROLE` granted via `GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE ...`). For org-level views: `ORGADMIN` role on the org account.
8. **Pagination + rate limits** — Not HTTP-based; governed by warehouse concurrency and query queue. Use a dedicated XS warehouse for Costly queries so they don't starve production.
9. **Gotchas** — (a) `ACCOUNT_USAGE` has a **45-min to 3-hour latency** — show the data-freshness timestamp in UI. (b) `ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY` is only available on the org account, not on member accounts. (c) Credit-to-dollar conversion requires joining `RATE_SHEET_DAILY` or reading `USAGE_IN_CURRENCY` directly — don't hardcode $2/credit. (d) `QUERY_ATTRIBUTION_HISTORY` was GA in late 2024; older deployments must fall back to `QUERY_HISTORY.CREDITS_USED_CLOUD_SERVICES + WAREHOUSE_METERING_HISTORY` pro-rated by `TOTAL_ELAPSED_TIME`. (e) `SERVICE_LEVEL` column ≠ Snowflake edition — it's the service family (`Compute`, `Storage`, etc.); the edition is on the contract.
10. **Citations** — [ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY](https://docs.snowflake.com/en/sql-reference/organization-usage/usage_in_currency_daily), [QUERY_ATTRIBUTION_HISTORY](https://docs.snowflake.com/en/sql-reference/account-usage/query_attribution_history), [ACCOUNT_USAGE schema](https://docs.snowflake.com/en/sql-reference/account-usage), [Cost management overview](https://docs.snowflake.com/en/user-guide/cost-understanding-overall).

Code: `snowflake_connector.py`.

---

## BigQuery

1. **Canonical data source** — `` `region-<REGION>`.INFORMATION_SCHEMA.JOBS_BY_PROJECT `` (or `JOBS_BY_ORGANIZATION` / `JOBS_BY_FOLDER`) for query-level cost attribution joined with the **BigQuery billing export** (see Gemini section) for invoice-authoritative totals. For storage: `INFORMATION_SCHEMA.TABLE_STORAGE_BY_PROJECT`. For reservations: `INFORMATION_SCHEMA.RESERVATIONS_TIMELINE_BY_PROJECT` and `ASSIGNMENTS_TIMELINE_BY_PROJECT`.
2. **Secondary / fallback** — `jobs.list` REST API (limited to 7 days, 1000 jobs max per call). Cloud Monitoring metric `bigquery.googleapis.com/job/num_in_flight` for live pipeline health (not cost).
3. **Fields returned** (`JOBS_BY_PROJECT`): `creation_time`, `project_id`, `user_email`, `job_id`, `job_type`, `statement_type`, `priority`, `query`, `labels`, `total_bytes_processed`, `total_bytes_billed`, `total_slot_ms`, `reservation_id`, `edition`, `cache_hit`, `dml_statistics.*`, `referenced_tables`, `destination_table`, `query_info.resource_warning`, `state`, `error_result`. `TABLE_STORAGE_BY_PROJECT`: `project_id`, `table_schema`, `table_name`, `creation_time`, `storage_last_modified_time`, `total_logical_bytes`, `active_logical_bytes`, `long_term_logical_bytes`, `total_physical_bytes`, `active_physical_bytes`, `long_term_physical_bytes`, `storage_billing_model`.
4. **Grouping dimensions** — `project_id`, `user_email`, `labels[<key>]`, `reservation_id`, `edition`, `statement_type`, `destination_table`.
5. **Pricing tier / SKU taxonomy** — Compute: on-demand $6.25/TB scanned OR reservations under Standard / Enterprise / Enterprise Plus editions priced in slot-hours. Storage: Physical ($0.02/GB/mo active, $0.01 long-term) OR Logical ($0.02/$0.01). Streaming inserts per-GB. BI Engine per-GB/hour.
6. **Cache / discount / commitment modifiers** — `cache_hit=TRUE` ⇒ free. Reservations are committed slot capacity (1y / 3y / Flex). Autoscaler slots priced per slot-second. Materialized views and BI Engine billed separately. Flat-rate legacy pricing deprecated — reservations replace it.
7. **Auth model** — Service account JSON with `roles/bigquery.resourceViewer` (for JOBS views) + `roles/bigquery.dataViewer` + `roles/bigquery.jobUser`. For org-wide JOBS_BY_ORGANIZATION: `roles/bigquery.resourceAdmin` at the org level.
8. **Pagination + rate limits** — Queries against `INFORMATION_SCHEMA` are regional — must specify `region-us` / `region-eu` etc. Jobs API: 1M req/day. INFORMATION_SCHEMA returns last 180 days only.
9. **Gotchas** — (a) `total_bytes_billed` is what you pay for; `total_bytes_processed` is informational (min billing 10 MB/query on-demand). (b) `JOBS_BY_PROJECT` excludes jobs run by service accounts in **other** projects — use `JOBS_BY_ORGANIZATION` for cross-project consolidation. (c) Reservations mean `total_bytes_billed = 0` even though the query consumed slots — join `total_slot_ms` × reservation rate for dollar estimate. (d) `edition` column only exists on post-2023 regions — older regions use `reservation_id` with `default-pricing-plan`. (e) `labels` on jobs only reflect labels at submission time; later label changes don't propagate.
10. **Citations** — [INFORMATION_SCHEMA.JOBS](https://cloud.google.com/bigquery/docs/information-schema-jobs), [TABLE_STORAGE_BY_PROJECT](https://cloud.google.com/bigquery/docs/information-schema-table-storage), [BigQuery pricing](https://cloud.google.com/bigquery/pricing), [Editions & reservations](https://cloud.google.com/bigquery/docs/editions-intro).

Code: `bigquery_connector.py`.

---

## Databricks

1. **Canonical data source** — `system.billing.usage` (Unity Catalog system table) joined with `system.billing.list_prices` to convert DBUs → USD. This is the billable-usage source of truth and mirrors what Databricks invoices. Available in all workspaces on Unity Catalog.
2. **Secondary / fallback** — Account Console **Billable Usage API** (`GET https://accounts.cloud.databricks.com/api/2.0/accounts/{account_id}/usage/download`) returns CSV/Delta export — use when the customer isn't on Unity Catalog. Workspace-level Clusters API for live compute inventory (not billing).
3. **Fields returned** (`system.billing.usage`): `record_id`, `account_id`, `workspace_id`, `sku_name`, `cloud`, `usage_start_time`, `usage_end_time`, `usage_date`, `custom_tags` (map), `usage_unit` (`DBU`), `usage_quantity`, `usage_metadata.cluster_id`, `usage_metadata.job_id`, `usage_metadata.warehouse_id`, `usage_metadata.notebook_id`, `usage_metadata.endpoint_name`, `usage_metadata.central_clean_room_id`, `usage_metadata.run_name`, `usage_metadata.job_run_id`, `usage_metadata.node_type`, `identity_metadata.run_as`, `identity_metadata.owned_by`, `record_type`, `ingestion_date`, `billing_origin_product` (`JOBS`, `ALL_PURPOSE`, `SQL`, `DLT`, `MODEL_SERVING`, `MOSAIC_AI_SERVING`, `VECTOR_SEARCH`, `ONLINE_TABLES`, `LAKEHOUSE_MONITORING`, `APPS`). `system.billing.list_prices`: `price_start_time`, `price_end_time`, `account_id`, `sku_name`, `cloud`, `currency_code`, `usage_unit`, `pricing.default`, `pricing.promotional.default`, `pricing.effective_list.default`.
4. **Grouping dimensions** — `workspace_id`, `sku_name`, `billing_origin_product`, `cloud`, `usage_metadata.job_id`, `usage_metadata.warehouse_id`, `custom_tags[<key>]`, `identity_metadata.run_as`.
5. **Pricing tier / SKU taxonomy** — SKU strings like `STANDARD_ALL_PURPOSE_COMPUTE`, `PREMIUM_JOBS_SERVERLESS_COMPUTE`, `ENTERPRISE_SQL_PRO_COMPUTE_US_EAST_1`. Plan tiers: Standard, Premium, Enterprise. Compute types: Classic vs Serverless. Photon-enabled SKUs priced higher.
6. **Cache / discount / commitment modifiers** — DBCU (Databricks Committed Units) commitments appear as `pricing.promotional.default` in `list_prices`. Spot discounts are cloud-provider side (AWS/Azure) — not on the Databricks side. Photon multiplier is already reflected in the SKU's `usage_quantity`. Serverless has no spot option.
7. **Auth model** — Databricks OAuth machine-to-machine (M2M) or Personal Access Token at the account level. For system tables: workspace PAT with SQL warehouse access + `USE SCHEMA system.billing`. For Billable Usage API: account-level token only (not workspace-level).
8. **Pagination + rate limits** — SQL-based (system tables) = warehouse concurrency. Account API: 100 req/min. Usage download is a CSV stream — no pagination.
9. **Gotchas** — (a) `system.billing.usage` has **4-hour latency** for most SKUs, **up to 24h** for serverless. (b) `list_prices` is regional — always filter by the workspace's cloud+region. (c) Serverless compute quantities are in DBUs like everything else but the per-DBU rate is 2-3× higher than classic — always join prices, don't hardcode. (d) Unity Catalog system tables must be enabled per-workspace (`system.billing` schema enablement). (e) `usage_metadata.job_run_id` joins to `system.lakeflow.job_run_timeline` for run-level duration, useful for anomaly detection.
10. **Citations** — [System table reference — billing](https://docs.databricks.com/aws/en/admin/system-tables/billing), [Billable usage log schema](https://docs.databricks.com/aws/en/admin/account-settings/usage-analysis), [Databricks pricing](https://www.databricks.com/product/pricing), [system.billing.list_prices](https://docs.databricks.com/aws/en/admin/system-tables/pricing).

Code: `databricks_connector.py`.

---

## dbt Cloud

1. **Canonical data source** — Admin API **v3** `GET https://cloud.getdbt.com/api/v3/accounts/{account_id}/runs` with `include_related=["job","run_steps","environment"]` for run attribution, plus Discovery API (GraphQL) for artifact metadata. Seat-count from `GET /api/v2/accounts/{account_id}/` (`developer_seats`, `read_only_seats`, `it_seats`).
2. **Secondary / fallback** — v2 runs endpoint still works but is being sunsetted. Artifact API `GET /api/v2/accounts/{account_id}/runs/{run_id}/artifacts/{path}` to download `manifest.json` / `run_results.json` for per-model timing.
3. **Fields returned** (runs): `id`, `account_id`, `project_id`, `environment_id`, `job_definition_id`, `status`, `status_humanized`, `run_steps[]`, `created_at`, `started_at`, `finished_at`, `duration`, `duration_humanized`, `queued_duration`, `run_duration`, `git_branch`, `git_sha`, `trigger.cause`, `run_generate_sources`, `has_docs_generated`, `job.name`, `environment.name`. Per-model (from `run_results.json`): `unique_id`, `execution_time`, `status`, `adapter_response.bytes_processed`, `adapter_response.slot_ms`.
4. **Grouping dimensions** — `project_id`, `job_definition_id`, `environment_id`, `git_branch`, `trigger.cause`, model tags from manifest.
5. **Pricing tier / SKU taxonomy** — Seat-based: Developer ($100/seat/mo), Team ($100/seat + $0.01/successful-model-run), Enterprise (contract). Plus warehouse-side compute cost attributed via `bytes_processed`/`slot_ms` in artifacts.
6. **Cache / discount / commitment modifiers** — No native commitment layer on dbt Cloud side. Enterprise customers get negotiated pricing reflected in the flat invoice, not in the API. Model-level compute savings come from the underlying warehouse (BigQuery cache, Snowflake result cache) — which dbt Cloud cannot see directly but the artifact's `adapter_response` reports.
7. **Auth model** — API Token (`Authorization: Token <token>`) generated under Profile Settings → API Tokens. Account-scoped tokens for dbt Cloud Admin actions. Service tokens (Enterprise) for machine-to-machine with finer permissions.
8. **Pagination + rate limits** — Offset-based (`limit`, `offset`). Hard limit: 100 rows per page. Rate limit: 60 req/min per token.
9. **Gotchas** — (a) `duration_humanized` includes queue time; `run_duration` is execution only — use `run_duration` for compute attribution, `queued_duration` to surface CI bottlenecks. (b) Cancelled runs have `status=30` — exclude from cost rollups. (c) `include_related=job` doesn't embed on v2; must use v3. (d) Successful-model-run billing (Team plan) requires counting `success` rows in `run_results.json`, not simply completed runs. (e) dbt Cloud's own UI doesn't show historical cost — customers often under-attribute transformation cost because they never count warehouse spend caused by dbt.
10. **Citations** — [dbt Cloud Administrative API](https://docs.getdbt.com/dbt-cloud/api-v3), [Discovery API (GraphQL)](https://docs.getdbt.com/docs/dbt-cloud-apis/discovery-api), [dbt Cloud pricing](https://www.getdbt.com/pricing).

Code: `dbt_cloud_connector.py`.

---

## Fivetran

1. **Canonical data source** — REST API v1 `GET https://api.fivetran.com/v1/account/billing/usage` for MAR at the account level (Starter/Standard/Enterprise plans) and `GET /v1/destinations/{destination_id}/billing/usage` for per-destination MAR. List connectors: `GET /v1/groups/{group_id}/connectors`. Connector-level MAR is **not** in the public API — only destination/account level.
2. **Secondary / fallback** — Log Service export to customer cloud storage (S3/GCS) gives per-sync row counts, but requires Enterprise plan. The `connector` details endpoint `GET /v1/connectors/{connector_id}` has `status.setup_state` and `succeeded_at` / `failed_at` but no MAR. Web UI CSV export as last resort.
3. **Fields returned** (`/account/billing/usage`): `start_timestamp`, `end_timestamp`, `mar_usage`, `mar_plan_limit`, `mar_plan_overage_rate`, `free_mar_usage`, `paid_mar_usage`, `estimated_cost`. Connectors (`/connectors`): `id`, `service`, `schema`, `connected_by`, `created_at`, `succeeded_at`, `failed_at`, `sync_frequency`, `paused`, `status.*`, `config.*` (sanitized).
4. **Grouping dimensions** — `destination_id`, `group_id`, `service` (connector type). **Not** per-source-table or per-connector at MAR resolution via public API.
5. **Pricing tier / SKU taxonomy** — MAR-based: Free Tier (<500K MAR), Starter, Standard, Enterprise, Business Critical. Higher tiers unlock features (PrivateLink, HVA, advanced transformations) but also different MAR rates. Free destinations (certain data apps) don't count.
6. **Cache / discount / commitment modifiers** — Annual commits with volume discounts — reflected in `estimated_cost` but the per-MAR rate is not exposed. Free historical sync windows (first 14 days free for new connectors).
7. **Auth model** — Basic auth with `api_key:api_secret`, generated under Account Settings → API Config. Account-scoped. No OAuth.
8. **Pagination + rate limits** — Cursor-based via `cursor` response field. Default 100 per page, max 1000. Rate limit: 100 req/min per key.
9. **Gotchas** — (a) MAR ≠ row count. A row that changes 10 times in a month = 1 MAR. Customers frequently mis-estimate by equating them. (b) Free connectors (HubSpot Marketing, Stripe Analytics, etc.) have $0 MAR but still appear in the connector list. (c) The `estimated_cost` field is USD regardless of contract currency — convert if needed. (d) Connector-level MAR attribution must be done by proxy via destination → schema → service mapping, since the API doesn't return it. (e) Paused connectors still report MAR until the sync cycle completes.
10. **Citations** — [Fivetran REST API](https://fivetran.com/docs/rest-api), [Billing usage endpoint](https://fivetran.com/docs/rest-api/account-management/account#getaccountbillingusage), [MAR pricing explainer](https://www.fivetran.com/pricing).

Code: `fivetran_connector.py`.

---

## Airbyte

1. **Canonical data source** — **Airbyte Cloud** (OAuth): `POST https://api.airbyte.com/v1/jobs/list` with `{workspaceIds, connectionId, jobType:'sync', updatedAtStart, updatedAtEnd}` for sync history + credit consumption. **Self-hosted/OSS**: `POST {host}/api/v1/jobs/list` (Configuration API) — different path, different schema. Cloud credits map 1:1 to dollars via plan.
2. **Secondary / fallback** — Cloud: `GET /v1/organizations/{org_id}/usage` for rollup. OSS: no billing concept — sync-job size × internal rate sheet the customer supplies.
3. **Fields returned** (Cloud `/v1/jobs`): `jobId`, `status`, `jobType`, `startTime`, `endTime`, `lastUpdatedAt`, `duration`, `bytesSynced`, `rowsSynced`, `connectionId`, `streams[]`, `attempts[]`. Credit usage via `/v1/organizations/{id}/usage`: `timeframeStart`, `timeframeEnd`, `connectionId`, `jobId`, `creditsConsumed`, `billingStatus`.
4. **Grouping dimensions** — `workspaceId`, `connectionId`, `sourceId`, `destinationId`, `jobType` (`sync`, `reset`, `clear`).
5. **Pricing tier / SKU taxonomy** — Cloud credits by data volume: rows for API sources, GB for database/file sources. Capacity plans (annual) vs usage-based. OSS is free but compute-cost-only (you run the infra).
6. **Cache / discount / commitment modifiers** — Capacity plans include committed credits with rollover (per contract). Cloud doesn't have a "cache" concept — incremental sync is the norm and reduces rowsSynced naturally.
7. **Auth model** — **Cloud**: OAuth 2.0 Client Credentials. Generate client ID+secret at cloud.airbyte.com → Settings → Applications. Exchange for bearer token at `https://api.airbyte.com/v1/applications/token`. **OSS**: per-user API key or basic auth depending on deployment; the Configuration API is unauthenticated by default on local installs (lock it down!).
8. **Pagination + rate limits** — Cursor via `next` in response. Cloud: 120 req/min per token. OSS: no formal limit.
9. **Gotchas** — (a) The OSS Configuration API (`/api/v1/*`) and Cloud public API (`/v1/*`) are **not** the same surface — payloads and field names differ. Detect deployment via host. (b) `bytesSynced` is uncompressed payload size, not the committed storage size (destinations dedupe). (c) OSS has no cost endpoint — you must synthesize cost from infra (EKS nodes, disk) yourself. (d) Cloud jobs in `running` state have no final `bytesSynced` — exclude from cost rollups until terminal. (e) Legacy v1 Configuration API endpoints (`/api/v1/jobs/list` on cloud) return 404 since 2024 — Cloud only speaks the new `/v1/*` shape.
10. **Citations** — [Airbyte API v1 reference](https://reference.airbyte.com/reference/getting-started), [OAuth client credentials](https://docs.airbyte.com/api-documentation), [Airbyte Cloud pricing](https://airbyte.com/pricing).

Code: `airbyte_connector.py` — currently uses one code path; add deployment detection + branching.

---

## Looker

1. **Canonical data source** — Looker's **System Activity** Explores queried via inline query API: `POST {instance}/api/4.0/queries/run/json` with an ad-hoc `Query` body against models `system__activity::history`, `system__activity::user`, `system__activity::dashboard`, `system__activity::query`, `system__activity::scheduled_plan`. These Explores are populated by Looker's internal i__looker database and are the authoritative usage source.
2. **Secondary / fallback** — `GET /api/4.0/queries/{query_id}/run/json` if you've pre-built a query. `GET /api/4.0/users` for seat count. `GET /api/4.0/projects` + `/api/4.0/projects/{id}/files` for model size proxies.
3. **Fields returned** (from `history`): `history.id`, `history.created_time`, `history.runtime`, `history.source`, `history.status`, `user.id`, `user.email`, `query.id`, `query.model`, `query.view`, `query.fields`, `query.filters`, `dashboard.id`, `dashboard.title`, `look.id`, `look.title`, `history.result_source` (`query`, `cache`, `etl`). From `query`: `query.id`, `query.fields`, `query.pivots`, `query.sorts`, `query.filters`, `query.limit`.
4. **Grouping dimensions** — `user.id`, `history.source` (`dashboard`, `look`, `scheduled_task`, `api`, `explore`), `history.result_source`, `query.model`, `dashboard.id`, `query.view`.
5. **Pricing tier / SKU taxonomy** — Seat-based by role: Viewer, Standard, Developer, Admin. No per-query cost — but Looker queries hit the underlying warehouse (Snowflake/BigQuery), so cost attribution requires joining history with warehouse query history on `history.completion_time` + rough time window.
6. **Cache / discount / commitment modifiers** — `history.result_source='cache'` ⇒ free (no warehouse cost). PDT (Persistent Derived Tables) rebuild cost hits the warehouse and shows in warehouse query history with the PDT name pattern `scratch.LR$...`. Looker has no native commitment layer; enterprise pricing is flat annual.
7. **Auth model** — API3 credentials: `POST /api/4.0/login` with `client_id` + `client_secret` returns short-lived `access_token`. Generate per-user under Admin → Users → Edit Keys. Admin role required for System Activity.
8. **Pagination + rate limits** — Inline query returns full result set (apply `query.limit`). List endpoints use `limit`+`offset`. Default concurrency: 10 parallel queries per host.
9. **Gotchas** — (a) System Activity is a **look** at Looker's internal Postgres — has delays during system-activity ETL (runs ~every 5 min on Cloud). (b) The `history.source` enum values are lowercase but inconsistently cased in older versions — normalize on read. (c) PDT rebuilds show up in warehouse history as the querying user `LOOKER`, not the human user — join with caution. (d) `queries/run/json` requires the full query body; you cannot reference a saved Look by ID with that endpoint. (e) Looker Embed queries appear with `history.source='regular'` which looks wrong — it actually means "non-dashboard, non-scheduled" and covers embed usage.
10. **Citations** — [Looker API 4.0 — queries](https://cloud.google.com/looker/docs/reference/looker-api/latest/methods/Query), [System Activity](https://cloud.google.com/looker/docs/usage-reports-with-system-activity-explores), [Looker pricing](https://cloud.google.com/looker/pricing).

Code: `looker_connector.py`.

---

## Tableau

1. **Canonical data source** — **Admin Insights** data source (Tableau Cloud) or **tsm views** (Server). Admin Insights is a prebuilt Tableau data source in every Cloud site; query it via `POST /api/3.22/sites/{site-id}/views/{view-id}/data` for CSV export, or connect with Tableau Server Client (TSC) Python lib. For job/background-task telemetry: `GET /api/3.22/sites/{site-id}/jobs`.
2. **Secondary / fallback** — REST API `GET /api/3.22/sites/{site-id}/users` for seat count; `GET /api/3.22/sites/{site-id}/workbooks` for content inventory; VizQL Data Service (headless) for custom query. Server-only: `tsm data-access` logs.
3. **Fields returned** (Admin Insights — `TS Users`, `TS Events`, `TS Site Content`, `TS Job Events`, `TS Background Tasks for Non Extracts`, `TS Background Tasks for Extracts`): `user_id`, `site_luid`, `user_email`, `site_role` (`Creator`, `Explorer`, `Viewer`), `last_login`, `created_at`, `event_type`, `workbook_id`, `view_id`, `datasource_id`, `project_id`, `duration` (for jobs), `status`, `job_type`. REST `/jobs`: `id`, `type`, `progress`, `createdAt`, `startedAt`, `endedAt`, `finishCode`.
4. **Grouping dimensions** — `site_role`, `project_id`, `user_id`, `event_type`, `workbook_id`, `job_type`.
5. **Pricing tier / SKU taxonomy** — Seat-based: Creator ($75/user/mo), Explorer ($42), Viewer ($15). Tableau Cloud bundles a data source quota; additional data management add-ons (Tableau Cloud Manage) priced separately.
6. **Cache / discount / commitment modifiers** — Extract refresh jobs consume backgrounder capacity — measure via `TS Background Tasks for Extracts`. Cloud doesn't expose backgrounder slot pricing directly; cost attribution is by seat × role. Enterprise discounts reflected in invoice only.
7. **Auth model** — **Personal Access Token (PAT)** preferred — `POST /api/3.22/auth/signin` with `{personalAccessTokenName, personalAccessTokenSecret, site.contentUrl}` returns a short-lived auth token. Generate under Account Settings → Personal Access Tokens. Site admin role needed for Admin Insights; server admin for cross-site.
8. **Pagination + rate limits** — Pagination via `pageNumber` + `pageSize` (max 1000). Cloud: 60 req/min per token. Server: governed by resource_manager.
9. **Gotchas** — (a) Admin Insights data is refreshed once every 24h — not real-time. (b) The `site.contentUrl` in the signin call is the URL slug (e.g. `mycompanyname`), not the site LUID. Common confusion. (c) The REST API's `3.22` version maps to 2023.3; check the compatibility matrix — older Server versions cap at 3.16 or 3.12. (d) Admin Insights is **only available on Tableau Cloud**; Server customers must build equivalent using PostgreSQL workgroup logs. (e) Jobs endpoint only returns the last 30 days; for history beyond, use Admin Insights extracts.
10. **Citations** — [Tableau REST API](https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api.htm), [Admin Insights](https://help.tableau.com/current/online/en-us/adminview_insights_manage.htm), [Tableau Cloud pricing](https://www.tableau.com/pricing/teams-orgs).

Code: `tableau_connector.py`.

---

## Omni

1. **Canonical data source** — Omni **System Activity** (internal topic) queried via `POST {instance}/api/v1/query/run` with an inline query body. Model: `system_activity`, topics: `queries`, `users`, `documents`, `models`. Omni's System Activity is analogous to Looker's and is the usage truth.
2. **Secondary / fallback** — `GET /api/v1/users` for seat count. `GET /api/v1/connections` to enumerate warehouse connections. Scheduled report API for digest-style aggregates.
3. **Fields returned** (`system_activity.queries`): `queries.id`, `queries.created_at`, `queries.user_id`, `queries.connection_id`, `queries.model_id`, `queries.topic`, `queries.fields`, `queries.filters`, `queries.duration_ms`, `queries.status`, `queries.result_source` (`cache`, `warehouse`, `materialization`), `queries.rows_returned`, `queries.document_id`, `queries.dashboard_id`. `system_activity.users`: `id`, `email`, `role`, `last_active`.
4. **Grouping dimensions** — `queries.user_id`, `queries.connection_id`, `queries.model_id`, `queries.document_id`, `queries.result_source`, `queries.status`.
5. **Pricing tier / SKU taxonomy** — Seat-based: Viewer, Explorer, Developer, Admin (~$35-75/user/mo depending on plan). No per-query cost; warehouse cost must be attributed via join.
6. **Cache / discount / commitment modifiers** — `queries.result_source='cache'` or `'materialization'` ⇒ no warehouse hit. Annual prepay discounts exist but aren't exposed via API.
7. **Auth model** — API key, header `Authorization: Bearer <key>`. Admin role required for System Activity. Generate under Admin → API Keys.
8. **Pagination + rate limits** — Inline query supports `limit` in body. List endpoints: cursor-based. Rate limit: documented at 60 req/min per key.
9. **Gotchas** — (a) Omni's public API surface was still stabilizing through 2025 — `v1` is the current live major version but expect additive changes. (b) `query/run` accepts either a topic-based query or raw SQL (`{ "sql": "..." }`); the topic-based form is what maps to semantic layer costs. (c) `result_source='materialization'` means served from an Omni-managed materialized view in the warehouse — there IS a warehouse cost for the refresh, attributed to Omni's service account user.
10. **Citations** — [Omni API reference](https://docs.omni.co/docs/API/introduction), [Omni System Activity](https://docs.omni.co/docs/content/system-activity), [Omni pricing](https://omni.co/pricing).

Code: `omni_connector.py` — currently lists connections only; upgrade to `query/run` against system_activity.

---

## Monte Carlo

1. **Canonical data source** — GraphQL API `POST https://api.getmontecarlo.com/graphql`. Key queries: `getMonitoredAssets` (for billable asset count), `getIncidents`, `getMonitors`, `getTableStats`. Monte Carlo bills on Monitored Assets Count (MAC), so `getMonitoredAssets` is the cost-authoritative endpoint.
2. **Secondary / fallback** — Account-level `getAccountRoles`, `getUser` (for auth smoke test), `getWarehouses` to enumerate sources. CSV export from the UI for air-gapped customers.
3. **Fields returned** (from `getMonitoredAssets`): `mcon`, `displayName`, `resource.name` (warehouse), `assetType` (`TABLE`, `VIEW`, `EXTERNAL`), `schema`, `database`, `isMonitored`, `monitorCount`, `lastUpdateUserTime`, `lastObserved`. `getIncidents`: `uuid`, `type`, `severity`, `status`, `createdTime`, `resolvedTime`, `mcon`, `assignedUser`. `getMonitors`: `uuid`, `monitorType`, `entities[]`, `creatorId`, `lastRun`.
4. **Grouping dimensions** — `resource.name` (warehouse), `assetType`, `monitorType`, `severity`, `database`, `schema`.
5. **Pricing tier / SKU taxonomy** — Per **Monitored Asset** tier with thresholds (e.g., 0-500 assets / 500-2500 / 2500+). Add-ons: Performance monitoring, Data Product health, Lineage+. Enterprise contracts bundle observability features.
6. **Cache / discount / commitment modifiers** — Annual commits with volume breaks negotiated in contract; not exposed via API. Test/dev environments sometimes excluded per contract — surface via `resource.accountId` tagging convention.
7. **Auth model** — Two headers: `x-mcd-id: <key_id>` and `x-mcd-token: <token>`. Both generated under Settings → API Keys. Account-scoped. Service accounts for M2M.
8. **Pagination + rate limits** — Cursor-based via `pageInfo.endCursor` on every paginated query. Default 200/page, max 1000. Rate limit: 10 req/sec (soft).
9. **Gotchas** — (a) The GraphQL schema evolves quickly — breaking field removals are communicated via changelog; pin your connector to specific query shapes. (b) `monitoredAssetsCount` in a summary query is authoritative, but raw `assets` list can over-count views that are also tracked as tables. (c) `getIncidents` without time filter defaults to last 7 days. (d) Older customers may have `mcon` vs `resourceMcon` inconsistencies across queries. (e) Monte Carlo does not expose the dollar amount — must map asset count × contract rate supplied by user.
10. **Citations** — [Monte Carlo GraphQL API](https://docs.getmontecarlo.com/docs/using-the-api), [Monitored Assets overview](https://docs.getmontecarlo.com/docs/monitored-tables-and-views), [Monte Carlo pricing guide](https://www.montecarlodata.com/pricing/).

Code: `monte_carlo_connector.py`.

---

## GitHub Actions

1. **Canonical data source** — **Enhanced Billing Platform API** (`GET /organizations/{org}/settings/billing/usage` and `/users/{username}/settings/billing/usage`). The legacy `/orgs/{org}/settings/billing/actions` and `/repos/.../actions/billing` endpoints **were deprecated and reach EOL in 2026**; the Enhanced API replaces them and is required going forward. Returns line-item usage with SKU breakdown.
2. **Secondary / fallback** — `GET /repos/{owner}/{repo}/actions/runs` + `/runs/{id}/timing` for per-run minute attribution when the billing API is unavailable (e.g., user-scoped PAT without billing permission). SKUs won't be available; cost estimated via list-price table.
3. **Fields returned** (Enhanced Billing): `date`, `product` (`Actions`, `Packages`, `Storage`, `Copilot`, `CodeSpaces`), `sku` (`Compute - Linux`, `Compute - Windows`, `Compute - macOS 12-core`, `Actions Storage`, `Copilot for Business`), `quantity`, `unit` (`Minutes`, `GigabyteHours`), `pricePerUnit`, `grossAmount`, `discountAmount`, `netAmount`, `organizationName`, `repositoryName`, `usageAt`, `costCenterName` (enterprise only), `workflowPath`, `workflowName`, `runAttribution`.
4. **Grouping dimensions** — `product`, `sku`, `repositoryName`, `workflowPath`, `costCenterName`, `date`.
5. **Pricing tier / SKU taxonomy** — Linux ($0.008/min), Windows ($0.016/min), macOS-3-core ($0.08/min), macOS-12-core ($0.16/min), Larger runners (Linux 4/8/16/32/64-core at tiered rates), GPU runners (T4, A10G). Public repos on hosted runners are free. Storage: $0.25/GB/mo beyond plan quota.
6. **Cache / discount / commitment modifiers** — No "cache" tier. Included minutes per plan (Free: 2000, Team: 3000, Enterprise: 50000) — appear as `discountAmount` offsetting `grossAmount`. Self-hosted runners are free (`netAmount=0`). Enterprise volume discounts contractual.
7. **Auth model** — Fine-grained PAT or OAuth App with `read:org` + billing read + workflow read. Personal access token (classic) with `admin:org` also works. GitHub App with `Organization administration: read` is preferred for prod.
8. **Pagination + rate limits** — Cursor-based (`cursor` param) or `page`/`per_page`. Primary rate limit: 5000 req/hr/token (15000 for GitHub Apps). Secondary rate limits on bursts.
9. **Gotchas** — (a) The legacy endpoints will return 410 Gone after the 2026 cutover — if your connector still calls `/settings/billing/actions`, it WILL break. Migrate now. (b) Enhanced Billing API returns `minutesUsedBreakdown.MACOS` multiplier accounted for — don't re-multiply. (c) macOS minutes have a 10× multiplier on plan-included minutes, but reported quantity is actual minutes run; only the price reflects the multiplier. (d) Self-hosted runner usage is logged with quantity but `netAmount=0` — useful for capacity planning. (e) `workflowPath` is only populated for runs initiated in the API window; older runs show empty.
10. **Citations** — [Enhanced Billing API](https://docs.github.com/en/rest/billing/enhanced-billing), [GitHub Actions billing](https://docs.github.com/en/billing/managing-billing-for-github-actions), [Legacy deprecation notice](https://docs.github.com/en/rest/billing/billing).

Code: `github_connector.py` — migrate from legacy endpoints before the 2026 EOL date.

---

## GitLab CI

1. **Canonical data source** — **Self-managed**: Compute/CI minutes via `GET /api/v4/groups/{id}/ci_minutes_usage` (group) and `/users/:id/ci_minutes_usage` (user). **GitLab.com SaaS**: same endpoints PLUS `GET /api/v4/groups/{id}/billable_members` for seat count. For per-project attribution: `GET /api/v4/projects/{id}/pipelines` with `?updated_after=` then `/pipelines/{id}/jobs` for per-job runner + duration.
2. **Secondary / fallback** — Admin area webhook or Prometheus exporter for self-managed installs. GraphQL API `query { group { ciMinutesUsage { ... } } }` mirrors REST but in a single call.
3. **Fields returned** (`ci_minutes_usage`): `minutes_used`, `minutes_used_breakdown.LINUX`, `minutes_used_breakdown.WINDOWS`, `minutes_used_breakdown.MACOS`, `shared_runners_minutes_limit`, `extra_shared_runners_minutes_limit`, `billing_cycle_start`, `billing_cycle_end`, `monthly_minutes_used`, `projects[].minutes`, `projects[].project_path`, `projects[].name`. Pipeline jobs: `id`, `status`, `stage`, `name`, `ref`, `started_at`, `finished_at`, `duration`, `queued_duration`, `runner.id`, `runner.description`, `runner.runner_type`, `runner.tag_list`.
4. **Grouping dimensions** — `project_id`, `runner_type` (`instance_type` / `group_type` / `project_type`), `runner.description`, `ref` (branch), `user_id`.
5. **Pricing tier / SKU taxonomy** — **Compute minutes**: Small/Medium/Large/XL/2XL runners on Linux, plus Windows/macOS. Multipliers — Linux 1x, Windows 2x, macOS 6x (subject to plan update). **Seat-based**: Free, Premium ($29/user/mo), Ultimate ($99/user/mo). Storage charged per-GB over included quota.
6. **Cache / discount / commitment modifiers** — Included compute minutes per plan (Free: 400 min, Premium: 10000, Ultimate: 50000) — track with `extra_shared_runners_minutes_limit` for purchased top-ups. Self-hosted runners are free. Saas-runner size multipliers baked into `minutes_used`.
7. **Auth model** — Personal / Project / Group Access Token (`PRIVATE-TOKEN` header) with `read_api` + `read_user` scope. For admin-level ci_minutes_usage at instance level: admin PAT on self-managed.
8. **Pagination + rate limits** — `page` + `per_page` (max 100). GitLab.com rate limit: 2000 req/min per user. Self-managed: configurable.
9. **Gotchas** — (a) `billable_members` count is only for GitLab.com SaaS; self-managed seat licensing is flat-fee per instance. (b) `minutes_used_breakdown` was added in 15.x — older instances don't have it; fall back to summing pipelines by runner tags. (c) Runner type `instance_type` on SaaS corresponds to the shared SaaS runner fleet; `project_type` = self-hosted on the project. (d) CI minutes reset at `billing_cycle_start` (monthly for SaaS, yearly for self-managed subscription). Don't roll up across reset boundaries. (e) macOS runners are in beta / limited access on GitLab.com — may not be available for all customers.
10. **Citations** — [GitLab CI minutes API](https://docs.gitlab.com/ee/api/ci_minutes.html), [Groups API — billable_members](https://docs.gitlab.com/ee/api/members.html#list-all-billable-members-of-a-group), [GitLab pricing](https://about.gitlab.com/pricing/).

Code: `gitlab_connector.py`.

---

# Cross-Cutting Standards to Apply Everywhere

## FOCUS 1.2 Schema Normalization Target

All connectors MUST normalize into `UnifiedCost` (see `app/models/platform.py`) whose fields map 1:1 onto **FOCUS 1.2** columns. This is the single source of truth for everything downstream — dashboard, anomaly detection, agent tooling, exports.

| `UnifiedCost` field | FOCUS 1.2 column | Notes |
|---|---|---|
| `date` | `ChargePeriodStart` (truncated to day) | Always UTC, `YYYY-MM-DD` |
| `platform` | `ProviderName` | `snowflake`, `anthropic`, `aws`, ... |
| `service` | `ServiceName` | Per-vendor: `snowflake`, `openai`, `s3`, ... |
| `resource` | `ResourceName` or `SkuId` | Warehouse/table/model/runner |
| `category` | `ServiceCategory` | `CostCategory` enum |
| `cost_usd` | `EffectiveCost` | Post-discount, pre-credit USD |
| `usage_quantity` | `PricingQuantity` | Tokens / credits / minutes / GB |
| `usage_unit` | `PricingUnit` | `tokens`, `credits`, `minutes`, `GB-mo` |
| `team` | `Tags['team']` | From cwd, project_id, custom_tags |
| `metadata` | Spill-over | Vendor-native fields kept verbatim |

When FOCUS 1.2 adds a column (e.g. `CommitmentDiscountId`, `ContractedCost`), extend `UnifiedCost` rather than stashing it in `metadata`. Only truly vendor-idiosyncratic fields belong in `metadata`.

## Honoring `pricing_overrides`

Every connector MUST accept an optional `pricing_overrides` dict in `credentials` of the form:

```
{
  "claude-opus-4-7": {"input": 12.0, "output": 60.0},
  "gpt-4.1":         {"input": 1.8, "output": 7.2},
  "USAGE_TYPE:compute": {"per_credit": 2.5}
}
```

Resolution precedence (highest wins):
1. Customer-supplied `pricing_overrides` (negotiated contract pricing).
2. Invoice-authoritative API (`Anthropic cost_report`, `OpenAI /costs`, `system.billing.list_prices`, FOCUS `EffectiveCost`).
3. Hardcoded `MODEL_PRICING` / `*_PRICING` tables in the connector module (list price).
4. Family-default fallback (e.g., Sonnet-tier for unknown Claude model).

Connectors should NEVER silently ignore an override. If a key is present but doesn't match any row, log a warning and fall through to (2)/(3)/(4).

## Unified Error Taxonomy

**Status: SHIPPED** — see `backend/app/services/connectors/errors.py` (100% test coverage in `backend/tests/test_connector_errors.py`).

All connector errors raise one of the following, every one a subclass of `CostlyConnectorError`:

| Error class | `code` | HTTP | When to raise |
|---|---|---|---|
| `InvalidCredentialsError` | `invalid_credentials` | 401 | Credential is invalid/revoked. Distinct from scope. |
| `ScopeMissingError` | `scope_missing` | 403 | Credentials valid but lack required scope (e.g., regular API key instead of admin). Carries `required_scope`. |
| `WarehouseNotFoundError` | `warehouse_not_found` | 404 | Target warehouse/workspace/project doesn't exist or the role can't see it. Carries `resource_name`. |
| `APIDisabledError` | `api_disabled` | 409 | Vendor API disabled on account (e.g., AWS Cost Explorer not enabled). |
| `RateLimitedError` | `rate_limited` | 429 | Vendor returned 429 or equivalent. Carries `retry_after` seconds. |
| `QuotaExceededError` | `quota_exceeded` | 429 | Daily quota exhausted. Carries `reset_at` (ISO). |
| `VendorDownError` | `vendor_down` | 502 | Vendor returned 5xx after backoff exhausted. |
| `SchemaDriftError` | `schema_drift` | 502 | Expected field missing in response — vendor changed shape. Carries `missing_field`. |
| `DataLaggedError` | `data_lagged` | 503 | Vendor replied 200 but with a clear "data not ready yet" signal. Not a failure; hint to retry later. |

Each error carries: `platform`, `endpoint`, `vendor_code`, `vendor_message`, `remediation_hint`, plus a computed `remediation_url` (→ `https://docs.costly.dev/errors/<code>`).

**Router integration:** `app.services.connectors.errors.register_connector_exception_handler(app)` is wired in `app/main.py`. Any route that raises a `CostlyConnectorError` automatically returns:

```json
HTTP <http_status>
{
  "error": {
    "code": "rate_limited",
    "message": "...",
    "platform": "anthropic",
    "endpoint": "/v1/organizations/usage_report/messages",
    "vendor_code": "429",
    "vendor_message": "...",
    "remediation_url": "https://docs.costly.dev/errors/rate_limited",
    "retry_after": 60
  }
}
```

Rate-limited responses also set the `Retry-After` HTTP header.

## Unified Retry / Backoff Policy

**Status: SHIPPED** — see `backend/app/services/connectors/retry.py` (100% test coverage in `backend/tests/test_connector_retry.py`).

Implemented once and applied via decorator `@with_retry(max_attempts=5)` on all HTTP calls. Works on sync AND async functions.

```python
from app.services.connectors.retry import (
    with_retry, raise_for_status_with_taxonomy,
)

@with_retry(max_attempts=5)
def fetch_page(self, cursor: str) -> dict:
    resp = httpx.get(self._url, headers=self._headers, params={"cursor": cursor})
    raise_for_status_with_taxonomy(resp, platform="anthropic", endpoint="/v1/usage")
    return resp.json()
```

- **Exponential backoff** with jitter: `min(60, base * 2**(attempt-1) + random(0, base))` seconds. Base defaults to 1.0s, cap to 60.0s.
- **Retry on** the transient taxonomy classes: `RateLimitedError`, `DataLaggedError`, `VendorDownError`, plus `httpx.RequestError` (connection-level). HTTP statuses `{429, 500, 502, 503, 504}` map onto these via `raise_for_status_with_taxonomy`.
- **Do not retry on** `InvalidCredentialsError`, `ScopeMissingError`, `WarehouseNotFoundError`, `APIDisabledError`, `SchemaDriftError`, `QuotaExceededError` — these are permanent. The non-retryable set always wins, even if a caller passes one of these in `retry_on_errors`.
- **Honor `Retry-After`** header (Anthropic, GitHub, Fivetran set it). `raise_for_status_with_taxonomy` parses the header into `RateLimitedError.retry_after`, and the decorator uses it as the MINIMUM sleep for that attempt (still capped by `backoff_cap`).
- **Abort after `max_attempts`** — the last transient exception is re-raised wrapped in `VendorDownError`, preserving `platform` / `endpoint` context so the router-level handler still produces a 502 with a meaningful message.
- Wrap **every** outbound HTTP call; the 15 existing connectors have ad-hoc try/except — refactor to the decorator as we touch each (next lanes' job; the plumbing is now in place).

## Token-Tier Naming Convention

All AI-inference connectors MUST expose their per-turn token counts via a dataclass matching `TokenUsage` from `claude_code_connector.py`:

```python
@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
```

Mapping table for vendors that don't use Anthropic's cache nomenclature:

| Costly field | Anthropic | OpenAI | Gemini | Notes |
|---|---|---|---|---|
| `input_tokens` | `uncached_input_tokens` | `input_tokens` − `input_cached_tokens` | `promptTokenCount` − cached | Uncached prompt only |
| `output_tokens` | `output_tokens` | `output_tokens` | `candidatesTokenCount` | — |
| `cache_read_tokens` | `cache_read_input_tokens` | `input_cached_tokens` | `cachedContentTokenCount` | Discounted tier |
| `cache_write_5m_tokens` | `cache_creation.ephemeral_5m_input_tokens` | n/a (no tier split) | n/a | Anthropic-only today |
| `cache_write_1h_tokens` | `cache_creation.ephemeral_1h_input_tokens` | n/a | n/a | Anthropic-only today |

For vendors without cache-tier distinctions, leave the extra fields at 0 and rely on the `cache_read_tokens` rollup. When a vendor introduces a new tier (e.g., OpenAI's expected multi-tier cache), add a typed field — do NOT coerce into an existing one.

Persistence: always materialize the full breakdown in `UnifiedCost.metadata` (as `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_5m_tokens`, `cache_write_1h_tokens`) so the dashboard can pivot on any tier without re-parsing vendor blobs.

---

## Maintenance Checklist When Adding / Updating a Connector

Before merging a connector change:

- [ ] Canonical endpoint matches this document (or this document has been updated with a dated note).
- [ ] `pricing_overrides` supported.
- [ ] Errors raise the unified taxonomy (no raw `Exception`).
- [ ] Retries go through `@with_retry`.
- [ ] AI-inference connectors emit the full `TokenUsage` breakdown in `metadata`.
- [ ] `test_connection()` distinguishes auth-valid-but-missing-scope from auth-invalid.
- [ ] Sample vendor response committed to `tests/fixtures/<platform>/` and unit test covers it.
- [ ] Docs link in section 10 is a 2026-current URL (vendors rotate doc domains).
