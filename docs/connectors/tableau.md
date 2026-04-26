# Tableau — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

Tableau (a Salesforce company) is the longest-established BI platform and has the most well-documented admin API of the three in this knowledge base. Tableau ships in two deployment modes that matter for connectors: **Tableau Cloud** (SaaS, Salesforce-hosted) and **Tableau Server** (self-hosted). Pricing is **per-seat, published**: Creator $75/user/mo, Explorer $42, Viewer $15, with a Site Admin Creator tier and an "Analytics Compute" credit bucket on Cloud. For cost attribution the authoritative source is **Admin Insights** on Cloud (a Tableau-maintained data source that's queryable like any other), plus the **REST API** (current = `3.22` on Cloud, up to `3.24` on newer Server builds) for jobs/views/users/tasks, plus — on Server only — the full **Postgres repository** for forensics. Costly's current `TableauConnector` uses API `3.22` PAT auth, fetches views and extract refresh tasks, applies a flat blended $35/user/mo heuristic, and emits daily license + extract-refresh rows. It's a good skeleton but thin: no Admin Insights usage, no per-user seat-tier cost, no per-workbook cost, no jobs history, and it conflates Cloud and Server behaviors.

## Pricing Model

Tableau publishes list prices (Cloud, as of 2025–2026):

- **Creator**: $75 / user / month (annual). Authors workbooks, publishes, uses Tableau Desktop + Prep.
- **Explorer**: $42 / user / month. Edits existing workbooks, web authoring.
- **Viewer**: $15 / user / month. Consumes dashboards only.
- **Site Administrator Creator**: Creator + admin powers; priced at Creator.
- **Tableau+**: premium add-on bundle (~$115/creator/mo and up — Einstein AI, Pulse, etc.).
- **Analytics Compute Credits (ACUs)** — Cloud-only metered bucket. Some features (Pulse, Einstein Insights, VizQL Data Service, large extract refresh jobs) draw from this bucket. Public list is "included credits per site tier" + overage at a published rate.
- **Tableau Pulse** and **Tableau Agent** — add-ons billed per Creator.
- **Tableau Server** — priced per-role like Cloud; paid annually with Salesforce contract; additional infra cost is on the customer.
- **Embedded Analytics** (Tableau Embedded) — separate licensing, typically **usage-metered** ("Embed Transactions" or per-user monthly active).

Sources:

- https://www.tableau.com/pricing/teams-orgs — published seat prices
- https://www.tableau.com/pricing/enterprise
- https://help.tableau.com/current/online/en-us/to_buy_or_admin.htm
- https://help.tableau.com/current/online/en-us/site_capacity.htm — Cloud site capacity / analytics credits
- https://www.tableau.com/blog/tableau-plus-benefits-ai-powered-analytics
- Vendr / G2 / TrustRadius benchmarks for negotiated pricing (often 20–40% off list at volume).

**Blended average check:** Costly currently uses $35/user/mo as a blended average. That's reasonable for a 10/30/60 Creator/Explorer/Viewer mix ($7.50 + $12.60 + $9 = $29.10) but understates Creator-heavy accounts. The customer should override per-tier.

## Billing / Usage Data Sources

### Primary

- **Admin Insights (Tableau Cloud only)** — a Tableau-maintained Project "Admin Insights" containing curated data sources:
  - `TS Events` — every user-facing action (sign-in, view, publish, refresh, download).
  - `TS Users` — all users with role and license info.
  - `TS Job Events` — background job outcomes.
  - `Login-based License Usage` — license draw-down telemetry.
  - `Visualization Load Time` — view render times.
  - These data sources are queryable via the **Metadata API (GraphQL)**, the REST API's `/vizql-data-service`, or directly from a Tableau Desktop connection.
- **REST API** — `https://<server>/api/<version>/...`. Current stable = 3.22 (Cloud), Server 2024.2+ supports 3.24. Key endpoints:
  - `POST /auth/signin` — PAT auth, returns auth token + `site.id` (LUID).
  - `GET /sites/{site-id}/users` — user roster, `siteRole`, `name`, `lastLogin`.
  - `GET /sites/{site-id}/views?includeUsageStatistics=true` — views + cumulative `totalViewCount`.
  - `GET /sites/{site-id}/workbooks` — workbooks, `ownerId`, `size`, `projectName`, `tags`.
  - `GET /sites/{site-id}/datasources` — published data sources.
  - `GET /sites/{site-id}/jobs` — job execution history (last 30 days; extract refreshes, subscriptions, flow runs, encryption). **This is the authoritative "did the refresh run" source**.
  - `GET /sites/{site-id}/tasks/extractRefreshes` — _scheduled_ extract refreshes (the schedules, not the runs).
  - `GET /sites/{site-id}/tasks/flowRuns` — Prep flow runs.
  - `GET /sites/{site-id}/schedules` (Server) / `GET /schedules` (Cloud) — schedule definitions.
  - `GET /sites/{site-id}/subscriptions` — subscription deliveries (email).
- **Metadata API (GraphQL)** — `POST /api/metadata/graphql`. Richest single endpoint. Gets workbooks, sheets, fields, upstream tables, embedded data sources, certifications, lineage, recent jobs. Lineage is the key lever for BI↔warehouse cost joins.
- **VizQL Data Service** (Cloud, 2024+) — headless VizQL endpoint that answers dashboard-style queries via REST/JSON; counts against ACUs.

### Secondary

- **Server Repository (PostgreSQL, Server-only)** — Tableau Server ships an embedded Postgres with a `workgroup`/`readonly` user. Tables: `http_requests`, `background_jobs`, `users`, `system_users`, `workbooks`, `views`, `hist_*`. Deepest forensics — but **not available on Cloud**.
- **TabCmd / Tableau REST CLI** — scripted admin, good for bulk content inventory.
- **`vizqlserver` and `backgrounder` log files** — raw logs on Server; contains query-plan info and long-running views.
- **Cloud Activity Log S3 export** — enterprise Cloud feature that writes JSON event logs to customer S3.
- **Salesforce Your Account (Cloud billing)** — authoritative spend; not a traditional API but accessible through the Salesforce MyAccount portal.
- **Tableau Pulse API** — separate endpoints under `/pulse/...` for Metrics and Insights.

### Gotchas

- **Cloud vs Server version**: Cloud is always on the latest API; Server is whatever the customer upgraded to. Costly hardcodes `3.22` — safe on Cloud, potentially stale on Server (and too new for very old Servers that stop at 3.19 or earlier). Discover the supported version via `GET /api/<any>/serverinfo` (unauthenticated).
- **Site LUID vs `contentUrl`**: signin takes `contentUrl` (the URL slug, e.g. `my-site`). The signin response returns the real site LUID. **All** subsequent calls use the LUID in the path. Costly has this right (`site.contentUrl` → `_site_id = site.id`) but the field naming is confusing — rename `site_id` in credentials to `site_content_url`.
- **Pagination**: `/users`, `/views`, `/workbooks` paginate with `pageNumber`/`pageSize` (max 1000). Must loop `pagination.totalAvailable`. Costly's `/users?pageSize=1` only reads `pagination.totalAvailable` — that's the one case where it is correct for a count but wrong for a roster.
- **`includeUsageStatistics=true`** on `/views`: returns cumulative `totalViewCount` and `hits` — **not** per-day. For time-series you must query Admin Insights `TS Events`.
- **Refresh tasks vs job runs**: `/tasks/extractRefreshes` returns _schedules_ (the recipe), not runs. `lastRunAt` on a schedule is the last run, but for per-day job counts use `/jobs?type=refresh_extracts` with `createdAtFrom`/`createdAtTo`. Costly's code reads `lastRunAt` only — undercount.
- **Jobs API**: capped at last 30 days and paginated. For longer history, ingest to Mongo yourself.
- **PAT expiry**: PATs expire after 15 days of inactivity on Cloud (configurable). For a long-running Costly deployment, **log in per-run** rather than caching the auth token beyond the 2-hour session window.
- **Sessions**: a successful signin token is valid for 2 hours by default; Costly's `_authenticate` memoizes once and never refreshes — same bug as Looker.
- **Site-level vs multi-site**: on Server, one deployment can have N sites; Costly assumes 1. Surface the full `/sites` list and let the user pick.
- **Cloud region**: different region pods (`10ax`, `us-east-1`, `eu-central-1` etc.) have different base URLs (`https://10ax.online.tableau.com`). The credential must capture pod.
- **ACU metering**: no official API for remaining-ACU today (as of 2026-04). The customer must share their Site Capacity page screenshot or overage invoice.
- **`vf_` URL params**: filter-state in view URLs creates new `view_id` variants in `TS Events`; dedupe by `workbook_id + view_name`.

## Schema / Fields Available

Most important fields across primary sources:

| Source | Field | Use |
|---|---|---|
| REST `/users` | `id`, `name`, `siteRole`, `lastLogin`, `authSetting` | Seat tier + last-active |
| REST `/views` (usage stats on) | `id`, `name`, `workbook.id`, `usage.totalViewCount` | View popularity |
| REST `/workbooks` | `id`, `name`, `project.id`, `owner.id`, `size`, `tags`, `createdAt`, `updatedAt`, `defaultViewId` | Content inventory |
| REST `/jobs` | `id`, `type`, `status`, `createdAt`, `startedAt`, `completedAt`, `extractRefreshJob.workbook.id`, `extractRefreshJob.datasource.id`, `extractRefreshJob.notes` | Actual refresh runs |
| REST `/tasks/extractRefreshes` | `schedule.id`, `schedule.frequency`, `workbook.id`/`datasource.id`, `lastRunAt`, `nextRunAt` | Scheduled refreshes |
| REST `/subscriptions` | `id`, `subject`, `user.id`, `schedule.id`, `content.id` | Subscription delivery (hidden cost) |
| Admin Insights `TS Events` | `userRoleName`, `eventType` (view_workbook, render_view, publish_workbook, refresh_extract), `itemLuid`, `itemName`, `eventTime`, `siteId` | Daily active, per-view, per-user |
| Admin Insights `TS Users` | `siteRoleName`, `licenseRoleName`, `lastLogin` | License inventory |
| Admin Insights `TS Job Events` | `jobType`, `jobStatus`, `completedAt`, `runtimeSec`, `itemLuid` | Job history at scale |
| Admin Insights `Login-based License Usage` | `licenseType`, `loginDate`, `userLuid` | LBLM billing |
| Metadata API | `workbook { id, name, upstreamDatasources { id, name, upstreamTables { schema, database { name } } } }` | Lineage |

## Grouping Dimensions

- **Per-workbook** — `workbook.id`. Maps to a team / product feature.
- **Per-view** — `view.id`. For fine-grained popularity.
- **Per-dashboard** (subset of view).
- **Per-user** — `user.id` / email, with `siteRole` tier.
- **Per-site** — multi-tenant Server.
- **Per-project** — `project.id` (Tableau's folder analog; aligns with org units).
- **Per-extract / per-datasource** — `datasource.id`.
- **Per-schedule** — `schedule.id`.
- **Per-job type** — `refresh_extract`, `run_flow`, `subscription`, `encrypt_extract`.
- **Per-license type** — Creator / Explorer / Viewer.
- **Per-pod / region** — for multi-region Cloud customers.
- **Per-connection** (upstream warehouse via Metadata API) — essential for BI↔warehouse join.

## Open-Source Tools

- **[tableau/server-client-python (TSC)](https://github.com/tableau/server-client-python)** — the official Python client. MIT. 1.7k+ stars, active. Handles auth, pagination, jobs, views, workbooks, Metadata API. **Costly should migrate to this.**
- **[tableau/rest-api-samples](https://github.com/tableau/rest-api-samples)** — official samples.
- **[tableau/hyper-api-samples](https://github.com/tableau/hyper-api-samples)** — Hyper (extract) format library.
- **[tableau/metadata-api-samples](https://github.com/tableau/metadata-api-samples)** — Metadata GraphQL examples.
- **[tableau/community-tableau-python-client](https://github.com/tableau/community-tableau-python-client)** — experimental.
- **[drewgillson/tabcmd](https://github.com/tableau/tabcmd)** — official TabCmd rewrite in Python.
- **[PyTableau](https://pypi.org/project/tableau-api-lib/)** — `tableau-api-lib` (divinorum-webb); MIT; alternative to TSC with finer-grained request control.
- **[tableau_tools](https://pypi.org/project/tableau-tools/)** — Bryant Howell; older but widely used.
- **Taco (Tableau Governance as Code)** — community efforts for content lifecycle automation.
- **[gain-metrics/warehouse-cost-attribution](https://github.com/)** — various dbt packages tagging Tableau workbooks as dbt exposures.
- **[Monitor](https://github.com/tableau/InteractiveContentMigration)** style repos — extract and diff content.
- **dbt `exposures:`** — first-class way to tie a Tableau dashboard to a dbt model; enables cross-tool lineage.
- **Catalog tools**: DataHub, Atlan, Secoda, Castor, OpenMetadata — all have Tableau ingesters.

## How Competitors Handle Tableau

- **Tableau's own Admin Insights** — set the benchmark. Every usage report Costly ships for Tableau will be compared to the out-of-the-box Admin Insights starter workbooks.
- **CloudZero** — Tableau integration pulls REST API + Cloud Billing export; dashboards for cost-per-workbook, idle seats, extract-refresh cost. https://www.cloudzero.com/blog/tableau-cost/
- **Vantage** — light-touch Tableau integration (user count + SKU mapping to invoice).
- **Apps for Tableau (Salesforce AppExchange)** — several ISV "Tableau usage analytics" apps (Wiiisdom Usage Analytics, Interworks "Lens", Snowflake Data Cloud Tableau App).
- **Wiiisdom Usage Analytics** (formerly Inside) — enterprise product for content lifecycle + cost. Good reference for feature surface.
- **Interworks "Lens"** — consultancy-built Tableau usage solution; pattern is identical: Repository + Admin Insights + Metadata API.
- **Portable.io** — Tableau metadata ETL into customer's warehouse.
- **Atlan / DataHub / Secoda / Castor** — for lineage & popularity, not cost.
- **Alvin / SelectStar** — lineage-heavy; Tableau is a sink in a warehouse-to-BI lineage tree.
- **Instacart / Robinhood / Airbnb engineering blogs** — all published versions of "how we built Tableau cost attribution"; patterns reinforce: PAT auth → jobs + Admin Insights → join to warehouse via workbook/datasource → attribute.
- **Uber's Databook** — internal, but public talks describe the exact same pipeline.
- **Sigma / ThoughtSpot / Hex** — competitor BIs that tout lower TCO vs Tableau; their marketing often quotes "your Tableau is costing X" — reinforces that this is a real buyer problem.

Dimensions every competitor tracks: seat count by role, seat spend, per-workbook views, per-workbook refresh time, idle content, scheduled subscription load, extract size vs live-connection mix, ACU burn.

## Books / Published Material

- **"Tableau Desktop: A Visual Analytics Toolkit"** — Joshua Milligan, multiple editions. Packt.
- **"The Big Book of Dashboards"** (Wexler, Shaffer, Cotgreave) — O'Reilly. Heavy on Tableau examples.
- **"Storytelling with Data"** (Cole Nussbaumer Knaflic) — cross-BI classic.
- **"Practical Tableau"** — Ryan Sleeper, O'Reilly.
- **"Innovative Tableau: 100 More Tips, Tutorials, and Strategies"** — Ryan Sleeper.
- **"Information Dashboard Design"** — Stephen Few (foundational).
- **"Tableau Your Data!"** — Dan Murray, Wiley.
- **"Communicating Data with Tableau"** — Ben Jones, O'Reilly.
- **"Mastering Tableau 2024"** — Marleen Meier, Packt.
- **Tableau Conference keynotes** (2024, 2025) — recorded on tableau.com/events; watch for "Tableau Next", "Tableau Agent", "Pulse", "VizQL Data Service".
- **Tableau Data Dev Day** — annual developer conference; REST/Metadata API sessions are gold for connector authors.
- **Tableau Community Forums / #TableauCommunity on X / #DataFam** — informal but authoritative troubleshooting.
- **Tableau Public gallery** — example workbooks, often including Admin Insights layouts.
- **Chris Love — LoveTableau.com** — performance best practices.
- **The Information Lab** blog / YouTube — UK consultancy; regularly publishes governance and licensing audits.

## Vendor Documentation Crawl

- https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api.htm — REST API reference
- https://help.tableau.com/current/api/metadata_api/en-us/index.html — Metadata API (GraphQL)
- https://help.tableau.com/current/online/en-us/adminview_insights_manage.htm — Admin Insights overview
- https://help.tableau.com/current/online/en-us/adminview_insights_datasources.htm — Admin Insights data source schemas
- https://help.tableau.com/current/online/en-us/to_buy_or_admin.htm — site roles / pricing
- https://help.tableau.com/current/online/en-us/site_capacity.htm — Cloud capacity / analytics credits
- https://help.tableau.com/current/server/en-us/perf_tuning.htm — performance best practices
- https://help.tableau.com/current/server/en-us/data_dictionary.htm — Server Postgres repository schema
- https://www.tableau.com/support/releases — release notes by version
- https://www.tableau.com/blog — product and pricing announcements
- https://dev.tableau.com/ — developer portal

## Best Practices (synthesized)

1. **Use Admin Insights first** — don't rebuild what Tableau already ships. Add value by joining to warehouse.
2. **Per-workbook cost**: allocate seat cost + extract cost + view compute to workbooks by access share.
3. **Idle content report** — workbook `updated_at` > 180 days AND `totalViewCount_last_90d == 0`.
4. **Seat right-sizing**: users with only `view_workbook` events in 90 days on a Creator seat → downgrade candidate.
5. **Extract mix**: track live vs extract queries. Big extracts that refresh hourly and are queried once a day = prime optimization.
6. **Subscription audit**: high-frequency subscriptions on low-view workbooks.
7. **Pulse / Einstein metering**: track ACU burn by feature.
8. **Workbook complexity**: # of sheets, # of data sources, size in MB — correlate with render time.
9. **Performance flags**: any workbook where VizQL render > 5s at p95.
10. **Dedicated service user**: a PAT-owning service account with Site Admin Explorer (can read Admin Insights, cannot publish).

## Costly's Current Connector Status

File: `backend/app/services/connectors/tableau_connector.py`

**What it does today:**

- Auth: `POST /api/3.22/auth/signin` with PAT name + secret + site `contentUrl`, memoizes `token` and LUID.
- `test_connection`: `GET /users?pageSize=1`.
- `fetch_costs(days)`:
  - User count (via pagination header only).
  - `/views?includeUsageStatistics=true&pageSize=100` (first page only).
  - `/tasks/extractRefreshes?pageSize=100` (first page only; uses `lastRunAt`).
- Cost model: `user_count * $35/mo / 30` daily license; views/refreshes attached as metadata.
- Emits:
  - `service="tableau", category=licensing` per day.
  - `service="tableau_extracts", category=serving` per day with `cost_usd=0`.

**What it does well:** correct PAT auth, correct 3.22 path, safe exception handling, right separation of licensing vs compute.

**What's broken / thin:**

1. Only the first 100 views / 100 tasks — missing everything else.
2. `lastRunAt` ≠ job runs; doesn't reflect real daily refresh volume.
3. Blended $35/user/mo regardless of Creator/Explorer/Viewer mix.
4. No Admin Insights ingestion at all.
5. `_get_view_usage` returns `total_views` cumulatively, not per-day; the `"date"` field expected in `fetch_costs` is never populated.
6. Loop `while current < end` creates one license row per day per user batch but `day_views` always 0 because the view payload has no date.
7. Session token not refreshed after 2-hour window.
8. No server version negotiation — 3.22 may 404 on very old Server builds.
9. No `site` enumeration; multi-site Server collapses to one.
10. Jobs API not used — actual refresh outcomes are invisible.
11. Pagination not implemented anywhere.
12. Metadata API (GraphQL) not used — no lineage to warehouse.
13. No Cloud pod detection.

## Gaps

- **Admin Insights ingestion** — the biggest single gap. Needs the Insights data source LUIDs per site + query via `/vizql-data-service` or export via Metadata API.
- **Per-seat-tier cost** — split `users` by `siteRole` (Creator / Explorer / Viewer / SiteAdministratorCreator / SiteAdministratorExplorer / Unlicensed), price each.
- **Job runs** — `/jobs?type=refresh_extracts&createdAtFrom=...` gives real daily counts and runtimes.
- **Per-workbook attribution** — group views and refresh jobs by `workbook.id`, emit a unified record per workbook/day.
- **Lineage to warehouse** — Metadata API to map workbook → upstream table → warehouse database → join to Snowflake/BigQuery cost.
- **Subscription cost** — enumerate `/subscriptions` + their schedules.
- **Flow / Prep costs** — `/tasks/flowRuns` + Prep Conductor credits.
- **ACU burn** — manual overlay for now; watch for public API.
- **Cloud pod auto-detection** — parse `server_url`.
- **Server repository support** — optional connector for on-prem customers with Postgres `readonly` user.
- **Session refresh** — honor 2-hour TTL.
- **Pagination everywhere**.
- **TSC migration** — replace hand-rolled httpx with `tableauserverclient`.

## Roadmap

**P0 — Correctness**

- Implement pagination on users/views/tasks.
- Switch from `/tasks/extractRefreshes.lastRunAt` to `/jobs?type=refresh_extracts` for daily counts.
- Track signin TTL + re-login.
- Server-version negotiation via `/serverinfo`.

**P1 — Per-tier cost + per-workbook**

- Classify users by `siteRole` + per-tier price (overrideable).
- Per-workbook daily row with view count and refresh runtime.

**P2 — Admin Insights**

- Discover Admin Insights data source LUIDs.
- Ingest `TS Events` and `TS Job Events` via Metadata API / VizQL Data Service.
- Daily active users, per-user action counts.

**P3 — Lineage + warehouse join**

- Metadata API GraphQL queries to pull workbook → datasource → database.name lineage.
- Join to Snowflake/BigQuery query-history by upstream table name / connection name.
- "Expensive Tableau Workbooks" report.

**P4 — Advanced**

- Subscriptions, Flow runs, Pulse/ACU telemetry (once APIs land).
- Server Postgres repository connector (opt-in).
- TSC migration with retries.
- Multi-site support.

## Change Log

- 2026-04-24: Initial knowledge-base created.
