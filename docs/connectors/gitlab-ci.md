# GitLab CI — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

GitLab CI/CD is the second-largest CI spend category for most dbt/data-platform teams — frequently under-reported because GitLab's unit is **compute minutes** (not wall-clock seconds) with a runner-size `cost_factor` multiplier that existing integrations ignore. Costly's current `gitlab_connector.py` pulls pipelines per project and sums `pipeline.duration / 60`, which is **wall-clock seconds of the entire pipeline** (including queue and concurrent parallel jobs summed) and does NOT equal billable compute minutes. The right source is `/groups/{id}/ci_minutes_usage` (group-aggregate) and `/projects/{id}/pipelines/{pid}/jobs` with each job's `queued_duration` / `duration` and its runner tag mapped to the correct `cost_factor`. GitLab.com SaaS costs $10 per 1,000 overage minutes and varies 1×–12× by runner size (6-12× for macOS). Namespace storage, GitLab Duo seats, and Dedicated instance charges are separate SKUs. The near-term work for Costly is: swap to the ci_minutes_usage endpoint, introduce a runner-size → cost_factor table, and expose project / runner-tag / job-name grouping.

## Pricing Model

**GitLab.com SaaS CI/CD compute minutes**:
- **Free** tier: 400 compute minutes/month/namespace (reduced from 2,000 in 2023)
- **Premium**: 10,000 compute minutes/month ($29/user/month billed annually)
- **Ultimate**: 50,000 compute minutes/month ($99/user/month billed annually)
- **Overage**: $10 per 1,000 additional compute minutes ($0.01/min effective)

**cost_factor multiplier by runner tier (SaaS)**:
- `saas-linux-small-amd64` (1 vCPU / 4 GB): **1×**
- `saas-linux-medium-amd64` (2 vCPU / 8 GB): **2×**
- `saas-linux-large-amd64` (4 vCPU / 16 GB): **3×**
- `saas-linux-xlarge-amd64` (8 vCPU / 32 GB): **6×**
- `saas-linux-2xlarge-amd64` (16 vCPU / 64 GB): **12×**
- `saas-linux-medium-arm64`: **2.5×** (ARM is discounted vs. equivalent x86)
- `saas-linux-large-arm64`: **5×**
- `saas-linux-small-amd64-gpu-standard`: **7×**
- `saas-macos-medium-m1`: **6×**
- `saas-macos-large-m2pro`: **12×**
- `saas-windows-medium-amd64`: **1×** (beta pricing)

A 10-minute run on a `large-amd64` burns **30 compute minutes** of the namespace quota.

**Public open-source projects**: 50,000 minutes/month on the GitLab for Open Source program (approval required).

**GitLab Duo** (AI pair-programming add-on):
- **Duo Pro**: $19/user/month (Code Suggestions + Chat)
- **Duo Enterprise**: $39/user/month (adds agentic capabilities)

**Namespace storage / shared runners cache**:
- 5 GB included on Free/Premium/Ultimate
- Overage: $60/year per 10 GB data pack

**LFS / container registry / package registry / artifacts**:
- All count against namespace storage
- Same overage ladder

**GitLab Dedicated** (single-tenant SaaS): custom pricing, typically ~$100K/year floor.

**Self-managed GitLab** (Enterprise Edition): per-user license, compute is the customer's own (K8s/EC2/VMware) — compute minutes concept doesn't apply.

**Sources**:
- https://about.gitlab.com/pricing/
- https://docs.gitlab.com/ee/ci/pipelines/compute_minutes.html
- https://docs.gitlab.com/ee/ci/runners/saas/linux_saas_runner.html
- https://about.gitlab.com/pricing/compute-minutes/

## Billing / Usage Data Sources

### Primary

**Group-level compute minutes usage**:
- `GET /api/v4/groups/{id}/ci_minutes_usage` — returns minutes consumed by sub-project, sub-group, and month
- `GET /api/v4/namespaces/{id}/ci_minutes_usage` — namespace-level (root group or user namespace)
- Schema: `[{minutes, shared_runners_duration, month: "YYYY-MM-DD", monthly_minutes_used, projects: [{name, minutes, ...}]}]`
- This is the **billable compute minutes** number — already multiplied by cost_factor

**Project pipelines**:
- `GET /api/v4/projects/{id}/pipelines` — filter `updated_after`, `status=success|failed|canceled`
- `GET /api/v4/projects/{id}/pipelines/{pipeline_id}` — single pipeline detail (`duration`, `queued_duration`, `coverage`)
- `GET /api/v4/projects/{id}/pipelines/{pipeline_id}/jobs` — per-job `duration`, `queued_duration`, `runner.description`, `runner.tag_list`, `name`, `stage`
- Jobs are the right granularity — each job runs on one runner with one cost_factor

**Runner enumeration**:
- `GET /api/v4/runners/all` — admin only; SaaS list
- `GET /api/v4/projects/{id}/runners` — runners visible to project
- Each runner has `tag_list` which maps to SKU (`saas-linux-medium-amd64`, etc.)

**Billable members** (seat count for per-user pricing):
- `GET /api/v4/groups/{id}/billable_members`
- Used for Duo seat cost attribution

**Namespace storage**:
- `GET /api/v4/namespaces/{id}` → `root_repository_size`, `storage_size`, `wiki_size`, `lfs_objects_size`, `build_artifacts_size`, `packages_size`, `snippets_size`, `uploads_size`

### Secondary

**Pipeline-level aggregation** (current Costly approach — flawed but available):
- `pipeline.duration` is the sum of all job `duration`s — concurrent parallel jobs are double-counted in wall-clock terms, which actually approximates billable minutes but does NOT apply cost_factor
- `pipeline.queued_duration` is wait time — NOT billed

**Events API** (for webhook/firehose):
- `POST /webhooks` with `pipeline events`, `job events` — real-time pipeline and job start/end
- Project-level and group-level webhooks available

**GitLab.com billing CSV export**:
- Admin settings → Usage Quotas → Export — monthly CSV of compute minutes and storage
- Matches ci_minutes_usage API output

**GraphQL API** (`/api/graphql`):
- Exposes `ciJobsStatistics`, `ciMinutes`, and pipeline fields
- Richer filtering than REST for specific analyses
- Rate-limited separately from REST

### Gotchas

1. **`pipeline.duration` is NOT compute minutes**. It is the sum of job durations but BEFORE cost_factor multiplication. For a pipeline with three 5-minute jobs on `saas-linux-large-amd64` (3×), the pipeline reports `duration=900` (15 min) but the billable compute is **45 minutes**.
2. **Pagination**: REST API returns 20 by default, max 100 per page. Must follow `Link: <...rel="next">` header. `x-next-page` header alone is lossy if consumer doesn't read `link`.
3. **Rate limits**: GitLab.com authenticated = 2,000 req/min, unauthenticated = 500 req/min. Secondary limit on `/projects/*/pipelines` of 600/min.
4. **Self-managed instances** vary — admin can configure rate limits per endpoint.
5. **Runner tag_list is free-form** — customers may use `prod-deploy`, `gpu`, etc. not just the SaaS SKU names. Map via a config table per customer.
6. **Concurrent jobs** — a pipeline with `parallel: 10` runs 10 concurrent jobs. Each counts separately. `pipeline.duration` field SUMS them; it's not a max.
7. **Retried jobs**: `retry: 2` counts the retry minutes too. Use `/jobs?include_retried=true` to see all attempts.
8. **Finished_at vs. updated_at**: filter by `updated_after` returns pipelines still being updated (e.g., deployment status changes); prefer `updated_after` + status in `["success", "failed", "canceled"]` to avoid double-counting.
9. **`shared_runners_duration`** is seconds on SaaS shared runners (billable). `duration` includes self-hosted runners (not billable). The distinction matters for cost attribution.
10. **Project move between groups**: `ci_minutes_usage` is attributed to the namespace at the time of consumption; moving a project doesn't retroactively reallocate.
11. **Group access vs. project access**: a token with only `read_api` on a project cannot call `/groups/{id}/ci_minutes_usage`. Need group-level owner/maintainer or a group access token.
12. **macOS runners are allowlist-only** on SaaS — pricing is 6-12× but availability is opt-in.
13. **Trigger tokens and scheduled pipelines** — `trigger.author` is null for scheduled, useful for budget-by-actor grouping.
14. **`duration` can be null** for still-running pipelines — filter `status=success|failed|canceled`.

## Schema / Fields Available

**Pipeline**:
```
id                  int
iid                 int  (project-scoped)
project_id          int
sha                 string
ref                 string  (branch or tag)
status              string
source              string  (push, web, schedule, trigger, merge_request_event, ...)
created_at          ISO 8601
updated_at          ISO 8601
started_at          ISO 8601
finished_at         ISO 8601
committed_at        ISO 8601
duration            int  (seconds, sum of job durations)
queued_duration     int  (seconds)
coverage            float (nullable)
user.username       string
```

**Job**:
```
id                  int
pipeline.id         int
status              string
stage               string
name                string
ref                 string
tag                 bool
coverage            float
created_at          ISO 8601
started_at          ISO 8601
finished_at         ISO 8601
duration            int  (seconds)
queued_duration     int
runner.id           int
runner.description  string
runner.active       bool
runner.is_shared    bool
runner.tag_list     [string]
user.username       string
allow_failure       bool
```

**ci_minutes_usage**:
```
[{
  month: "2026-04-01",
  minutes: 4821,                 (cost_factor applied)
  shared_runners_duration: 289260,  (seconds, raw)
  monthly_minutes_used: 4821,
  projects: [
    {name, shared_runners_duration, minutes}
  ]
}]
```

## Grouping Dimensions

- **Root group / Top-level namespace**: billing boundary
- **Sub-group**: team-level cost attribution
- **Project**: the workhorse dimension
- **Pipeline source**: push / merge_request / schedule / trigger / web / api / pipeline / parent_pipeline
- **Branch / Ref**: `main` vs. feature branches
- **Stage**: build / test / deploy — test is almost always largest
- **Job name**: `rspec:parallel/1 4`, `eslint`, `dbt-run`, etc.
- **Runner SKU / tag**: `saas-linux-small-amd64`, `saas-linux-large-amd64`, self-hosted group, `gpu`
- **Actor**: committer / scheduled / trigger token
- **Merge request**: MR-originated pipelines can be attributed to a PR/MR ID
- **Environment**: deployment jobs target an environment (`production`, `staging`, `review/*`)

## Open-Source Tools

- **gitlab-runner** — https://gitlab.com/gitlab-org/gitlab-runner — MIT — the self-hosted runner binary. Relevant because self-hosted is the #1 cost-reduction lever on GitLab.
- **elettronica/gitlab-ci-analytics** — niche but useful reporting scripts.
- **PrivateBin/pipeline-monitor** — community dashboards.
- **prometheus/pushgateway + gitlab-ci-pipelines-exporter** — https://github.com/mvisonneau/gitlab-ci-pipelines-exporter — MIT — Prometheus exporter that scrapes pipelines and jobs; widely deployed; closest thing to an OSS cost dashboard.
- **python-gitlab** — https://github.com/python-gitlab/python-gitlab — LGPL — official-ish Python client; covers all REST endpoints.
- **go-gitlab** (xanzy) — https://github.com/xanzy/go-gitlab — Apache-2.0 — Go client.
- **gitlab-terraform-provider** — https://gitlab.com/gitlab-org/terraform-provider-gitlab — MIT — useful for IaC-managed runners and groups.
- **gitlab-ci-local** — https://github.com/firecow/gitlab-ci-local — MPL-2.0 — local CI execution, similar to `act` for GitHub.
- **cichecker** and similar community linters — surface slow-stage anti-patterns.
- **dbt-gitlab** (the GitLab company's own dbt repo) — https://gitlab.com/gitlab-data/analytics — public reference for a complex GitLab-CI-driven dbt project, case study for optimization.

No mature OSS cost dashboard for GitLab.com exists. `gitlab-ci-pipelines-exporter` has duration metrics but no cost multiplication.

## How Competitors Handle These

- **GitLab Observability (ex-Opstrace)** — https://docs.gitlab.com/ee/operations/observability/ — GitLab's own in-house observability; shows pipeline timing and counts. Does NOT surface $ cost in a unified way.
- **GitLab "Value Stream Analytics"** — per-stage lead time; no cost.
- **Datadog GitLab CI integration** — https://docs.datadoghq.com/integrations/gitlab/ — monitors pipelines via webhooks. Not cost.
- **CloudZero CI/CD module** — generic CI/CD cost ingestion; GitLab is a supported source.
- **Vantage** — has a GitLab integration in beta (as of 2026).
- **CloudChipr** — generic multi-cloud FinOps; GitLab CI is surfaced via compute minutes API.
- **Harness CCM** — CI cost for Harness's own CI only; no native GitLab cost.
- **IBM Apptio / Cloudability** — high-end FinOps; support GitLab via CSV upload, not native.
- **Bearer / Snyk** — security-focused, not cost.
- **Flightcontrol / Render** — PaaS competitors, not GitLab-specific.

Costly's opportunity: native GitLab multi-SKU cost ingestion with runner cost_factor handled correctly + MR-level cost attribution (dbt PR cost, deploy cost per MR) — something no current vendor does well.

## Books / Published Material

- **"The DevOps Handbook" (Kim, Debois, Willis, Humble 2021)** — 2nd ed chapter on pipeline economics.
- **"Cloud FinOps" 2nd ed** — includes CI/CD allocation patterns.
- **GitLab Handbook** — https://handbook.gitlab.com/ — extremely detailed internal Ops/Finance practices; notes on their own compute minute spend.
- **GitLab Data Team Handbook** — https://handbook.gitlab.com/handbook/business-technology/data-team/ — their dbt-on-GitLab-CI experience; real-world slow-pipeline case study.
- **FinOps Foundation CI/CD Allocation patterns**.
- **"Accelerate" (Forsgren et al)** — pipeline duration as lead-time proxy.
- **Sid Sijbrandij's GitLab Summit talks** — pricing rationale for the 2023 compute-minute cut from 2,000 → 400.
- **GitLab Unfiltered YouTube** — engineering deep-dives on runners and autoscaling.

## Vendor Documentation Crawl

- https://docs.gitlab.com/ee/api/ci_minutes.html — compute minutes API reference
- https://docs.gitlab.com/ee/api/pipelines.html — pipelines REST endpoints
- https://docs.gitlab.com/ee/api/jobs.html — jobs REST endpoints
- https://docs.gitlab.com/ee/api/runners.html — runners API
- https://docs.gitlab.com/ee/ci/pipelines/compute_minutes.html — customer-facing explainer
- https://docs.gitlab.com/ee/ci/runners/saas/linux_saas_runner.html — SKU ladder and cost_factor
- https://docs.gitlab.com/ee/ci/runners/saas/macos_saas_runner.html — macOS SKUs
- https://docs.gitlab.com/ee/user/packages/ — Packages / Registry / LFS storage SKUs
- https://docs.gitlab.com/ee/administration/settings/account_and_limit_settings.html — rate limits
- https://docs.gitlab.com/ee/api/rest/index.html — pagination headers and auth
- https://docs.gitlab.com/ee/user/admin_area/settings/usage_ping.html — usage telemetry
- https://about.gitlab.com/pricing/compute-minutes/ — canonical compute-minute pricing
- https://docs.gitlab.com/ee/api/graphql/reference/ — GraphQL schema reference

## Best Practices (synthesized)

1. **Use `ci_minutes_usage`** as the ground truth — cost_factor is already applied.
2. **When `ci_minutes_usage` is not available** (project access only, not group), walk `/projects/{id}/pipelines/*/jobs` and apply a local cost_factor table per runner tag.
3. **Filter `runner.is_shared=true`** for SaaS billing — self-hosted runners are not billed per minute.
4. **Cache job responses** by job ID (immutable once `finished_at` is set) — 30-day TTL.
5. **Map tag_list → SKU** with a configurable lookup; default to 1× if unknown.
6. **Break down by MR** — `pipeline.source=merge_request_event` + `merge_request_id` correlates cost to code changes.
7. **Break down by schedule** — scheduled pipelines bucket should be separated in showback.
8. **Surface `queued_duration`** — high queue times indicate starvation of a specific runner tier; recommend migrating to a tier with higher capacity (or self-hosted).
9. **Storage SKU** — pull `namespace.storage_size` separately and list as its own cost line; namespace storage overage is common and underestimated.
10. **Duo seat allocation** — separate per-user line item, not per-minute.
11. **Compute minutes reset monthly** on the first of the month UTC — align date filters accordingly.
12. **Respect pagination** — always follow `Link: rel="next"`.

## Costly's Current Connector Status

File: `backend/app/services/connectors/gitlab_connector.py`

- **Class**: `GitLabConnector(BaseConnector)` with `platform = "gitlab"`
- **Auth**: `credentials["token"]` as `PRIVATE-TOKEN` header; optional `instance_url`, `group_id`, `project_ids`
- **Connection test**: GET `/user`
- **Primary fetch**: lists projects → for each, lists pipelines filtered by `updated_after` and `status=success` → sums `pipeline.duration / 60` per day
- **Pricing table**: hard-coded `RUNNER_PRICING = {"linux": 0.008, "windows": 0.016, "macos": 0.08, "saas-linux-small-amd64": 0.008, "saas-linux-medium-amd64": 0.016, "saas-linux-large-amd64": 0.032}`
- **Category**: `CostCategory.ci_cd`
- **Known issues**:
  - Only fetches `status=success` pipelines — ignores failed/canceled, which also consume minutes
  - `pipeline.duration` is summed job durations; applying a flat `$0.008/min` ignores cost_factor (under-counts large/xlarge/2xlarge usage by 3-12×)
  - No use of `ci_minutes_usage` endpoint — the one that's actually authoritative
  - Hard-codes `RUNNER_PRICING["linux"]` even though the map has more entries — always uses Linux small rate
  - No pagination — misses pipelines beyond per_page=100
  - Silent `except Exception: continue` swallows errors
  - No per-job breakdown — can't attribute cost to specific jobs
  - No runner tag ingestion — can't break down by runner size
  - Ignores GitLab Duo seats, namespace storage, Packages/LFS
  - No MR / branch / actor grouping
  - No self-hosted vs. shared runner distinction

## Gaps

1. Use `/groups/{id}/ci_minutes_usage` as primary source (cost_factor already applied)
2. Per-job ingestion with runner.tag_list → SKU mapping → cost_factor multiplier
3. Pagination with `Link` header
4. Include failed/canceled pipelines (they consume minutes too)
5. Namespace storage as separate cost line
6. GitLab Duo seat cost (separate line, not minute-based)
7. Self-hosted vs. shared runner separation
8. MR-level and actor-level attribution
9. Webhook receiver for near-real-time pipeline ingestion
10. GraphQL fallback for customers who prefer it
11. Multi-instance support (self-managed + GitLab.com together)
12. Billing CSV import path for customers without API access

## Roadmap

- **Phase 1**: replace sum-of-pipeline-duration with `ci_minutes_usage` call at namespace level
- **Phase 2**: per-job fetch with runner tag → SKU → cost_factor table; allow customer to override factors
- **Phase 3**: namespace storage + Packages/LFS cost ingestion
- **Phase 4**: Duo seat ingestion (via `billable_members` + Duo add-on detection)
- **Phase 5**: webhook receiver for pipeline/job events
- **Phase 6**: MR-cost attribution (per-PR "this PR cost $X" card)
- **Phase 7**: self-managed GitLab support (detects `instance_url != gitlab.com`, skips compute minutes, surfaces storage/Duo only)
- **Phase 8**: runner autoscaling recommendations (detect high queue times on large tier)

## Change Log

- 2026-04-24: Initial knowledge-base created
