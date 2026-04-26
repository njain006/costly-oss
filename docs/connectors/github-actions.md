# GitHub Actions — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

GitHub Actions is where a huge share of modern CI/CD spend lives — it is metered per-minute by runner OS and machine size, with Windows at 2x and macOS at 10x the Linux rate. Costly already ships a GitHub connector (`github_connector.py`) that uses the **legacy** `/orgs/{org}/settings/billing/actions` endpoint plus a workflow-run fallback. The legacy endpoint is deprecated and scheduled for removal; GitHub's replacement is the **Enhanced Billing Platform API** (`GET /organizations/{org}/settings/billing/usage`), which returns itemized `usageItems` with SKU, cost, quantity, and unit across Actions, Packages, LFS, Copilot, and Codespaces in one shape. The near-term work is: migrate to the enhanced API, keep the legacy endpoint as a fallback until it EOLs, correctly handle large-runner SKUs (4/8/16/32/64-core tiers), and expose per-repo / per-workflow / per-runner-size grouping dimensions. Existing code under-prices large runners, treats all Linux runners as `$0.008/min`, and pulls per-run `/timing` for every run (10K+ runs/month = rate-limit risk).

## Pricing Model

**Included minutes per plan** (reset monthly, only apply to private repos, public repos are free):
- Free: 2,000 min/mo, 500 MB Packages storage
- Team: 3,000 min/mo, 2 GB storage
- Enterprise Cloud: 50,000 min/mo, 50 GB storage

**Standard runner pricing (per-minute, Linux baseline)**:
- Linux (2-core): $0.008/min (1x multiplier)
- Windows (2-core): $0.016/min (2x multiplier)
- macOS (3-core Intel): $0.08/min (10x multiplier)
- macOS (12-core M1 / `macos-latest-xlarge`): $0.16/min

Minutes consumed against the included grant are multiplied by the runner multiplier — so 1 macOS minute burns 10 Linux minutes of your grant. Overage billed at the listed per-minute rate.

**Large hosted runners** (separate SKUs, billed per actual minute, no multiplier applied — the base rate already reflects the size):
- Linux 4-core: $0.016/min
- Linux 8-core: $0.032/min
- Linux 16-core: $0.064/min
- Linux 32-core: $0.128/min
- Linux 64-core: $0.256/min
- Windows 8-core: $0.064/min
- Windows 16-core: $0.128/min
- Windows 32-core: $0.256/min
- Windows 64-core: $0.512/min
- GPU runners (T4, A10): priced separately, roughly $0.07-0.21/min

**Self-hosted runners**: free of charge for Actions minutes; customer pays underlying compute (AWS/GCP/Azure) — surfaces under those connectors, not GitHub.

**Other GitHub SKUs that appear on the same bill**:
- **Packages**: $0.25 / GB-month storage + $0.50 / GB data transfer (first 1 GB transfer free; included storage varies by plan)
- **Git LFS**: $5 / 50 GB / month for both storage and bandwidth as a "data pack"
- **Copilot Business**: $19 / user / month
- **Copilot Enterprise**: $39 / user / month
- **Codespaces**: $0.18/hr (2-core) up to $2.88/hr (32-core), plus $0.07/GB-month storage
- **Advanced Security**: $49 / committer / month

**Sources**:
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://docs.github.com/en/billing/managing-billing-for-your-products/about-billing-for-github-actions
- https://github.com/pricing
- https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-copilot

## Billing / Usage Data Sources

### Primary

**Enhanced Billing Platform API** (the way forward, GA since mid-2024):
- `GET /organizations/{org}/settings/billing/usage`
- `GET /enterprises/{enterprise}/settings/billing/usage`
- `GET /users/{username}/settings/billing/usage`
- Returns an array of `usageItems`, each with: `date`, `product` (Actions / Packages / Copilot / Codespaces / Shared Storage / LFS), `sku` (e.g. "Compute - UBUNTU", "Compute - UBUNTU 16-core"), `quantity`, `unitType` (minutes / GB / gigabyte-hours / user-month), `pricePerUnit`, `grossAmount`, `discountAmount`, `netAmount`, `organizationName`, `repositoryName`, `workflowPath`.
- Supports `?year=`, `?month=`, `?day=`, `?hour=` filters — returns CSV-style itemization suitable for direct ingestion.
- Docs: https://docs.github.com/en/rest/billing/enhanced-billing

**Enterprise Cloud billing export to S3 / Azure Blob**:
- Daily CSV exports of the same usage data
- Schema matches enhanced API
- Path: org settings → Billing → Usage → Export (or via API)
- Best for > 10K-run orgs where hitting the REST API repeatedly is wasteful

### Secondary

**Legacy per-product billing APIs** (still alive in 2026, deprecation announced, confirmed retirement window is mid-to-late 2026):
- `/orgs/{org}/settings/billing/actions` → `{total_minutes_used, total_paid_minutes_used, included_minutes, minutes_used_breakdown: {UBUNTU, MACOS, WINDOWS, ubuntu_4_core, ...}}`
- `/orgs/{org}/settings/billing/packages`
- `/orgs/{org}/settings/billing/shared-storage`
- `/users/{user}/settings/billing/actions` (personal accounts)

**Workflow-run aggregation** (what Costly falls back to today):
- `GET /repos/{owner}/{repo}/actions/runs` — list runs (filter by `created`, `status`, `branch`, `event`, `actor`)
- `GET /repos/{owner}/{repo}/actions/runs/{run_id}/timing` — `{billable: {UBUNTU: {total_ms, jobs, job_runs: [{job_id, duration_ms}]}, MACOS: {...}}}`
- `GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs` — per-job runner labels (`runner_name`, `labels`) — needed to attribute to a specific runner SKU
- `GET /repos/{owner}/{repo}/actions/workflows/{workflow_id}/timing` — aggregate per-workflow timing (org-level)
- `GET /repos/{owner}/{repo}/actions/cache/usage` — repo-level Actions cache storage (counts against Packages)

**Webhooks** (push instead of poll):
- `workflow_run` event with `action: completed` — fires with the run ID, timing, conclusion
- Useful for near-real-time cost tracking without polling
- Setup: org or repo webhooks pointed at the Costly backend

### Gotchas

1. **Rate limits**: Personal access tokens and GitHub Apps get 5,000 req/hr primary + secondary rate limits for "resource-intensive" endpoints. A 10K-run/month org calling `/timing` per run hits the limit before day's-end.
2. **`/timing` is expensive**: it fires up internal workers to compute billable minutes per job. Prefer the aggregated `workflow_run.billable` field from the run list or switch to the enhanced API.
3. **SKU shape is NOT consistent** between legacy and enhanced APIs. Legacy `minutes_used_breakdown` uses keys like `UBUNTU`, `MACOS`, `WINDOWS`, `ubuntu_4_core`, `ubuntu_8_core`, `macos_12_core`. Enhanced API uses `sku: "Compute - UBUNTU 16-core"` as a string.
4. **Multipliers vs. large-runner base rates**: the 2x/10x multipliers apply to standard 2-core runners only. Large runners are already billed at their actual cost — applying the multiplier double-counts. Costly's current `_fetch_org_billing` hard-codes `$0.008` for all Linux OS minutes, which under-counts large-runner spend.
5. **Internal actors / scheduled runs**: filtering out `dependabot[bot]` or scheduled workflows is a common analysis requirement — `actor.login` is only in the run payload, not the billing payload.
6. **Private vs. public repos**: public-repo minutes are $0 and don't appear in billing, but do appear in `/timing`. Filter by `repo.private == true` when aggregating from workflow runs.
7. **Run duration != billable minutes**: `run.run_duration_ms` is wall-clock; billable minutes are rounded up per-job to the nearest minute. 10 jobs x 10 seconds = 10 billable minutes, not 2.
8. **GitHub Enterprise Server (GHES)**: no Actions billing API at all. Customers run self-hosted, cost = underlying infra.
9. **Secondary rate limits on concurrent requests**: > 60 concurrent requests triggers a soft ban. Use `asyncio.Semaphore(10)` or similar.
10. **Authorization model changed**: enhanced API requires a fine-grained PAT with `Plan: Read` OR a GitHub App with `administration:read`. The `repo` scope alone is insufficient.

## Schema / Fields Available

**Enhanced `usageItems` row**:
```
date                string  (ISO 8601 date)
product             string  (Actions, Packages, Codespaces, Copilot, ...)
sku                 string  ("Compute - UBUNTU", "Compute - UBUNTU 16-core", ...)
quantity            float   (minutes, GB, user-months)
unitType            string  (minute, gigabyte, user-month)
pricePerUnit        float   (USD)
grossAmount         float
discountAmount      float
netAmount           float
organizationName    string
repositoryName      string  (nullable)
workflowPath        string  (nullable, ".github/workflows/ci.yml")
```

**Workflow run object** (for fallback mode):
```
id                  int
name                string
workflow_id         int
head_branch         string
event               string  (push, pull_request, schedule, ...)
actor.login         string
created_at          ISO 8601
updated_at          ISO 8601
run_started_at      ISO 8601
run_attempt         int
run_number          int
conclusion          string  (success, failure, cancelled, skipped)
status              string
repository.full_name   string
repository.private  bool
runner_name         string  (set post-completion)
runner_group_name   string
```

**Timing object** (`/runs/{id}/timing`):
```
billable.UBUNTU.total_ms         int
billable.UBUNTU.jobs             int
billable.UBUNTU.job_runs[]       [{job_id, duration_ms}]
billable.MACOS.*
billable.WINDOWS.*
run_duration_ms                  int  (wall clock)
```

## Grouping Dimensions

- **Org / Enterprise**: top-level aggregation for cost allocation
- **Repository**: most common showback dimension
- **Workflow**: `.github/workflows/*.yml` — which pipeline costs the most
- **Job**: individual jobs within a workflow (build, test, deploy)
- **Runner OS**: ubuntu / windows / macos
- **Runner Size**: 2-core / 4-core / 8-core / 16-core / 32-core / 64-core / GPU
- **Actor**: committer / PR author / `dependabot[bot]` / `github-actions[bot]`
- **Event**: push, pull_request, schedule, workflow_dispatch, release
- **Branch**: main vs. feature branches — feature branches dominate cost in PR-heavy teams
- **Self-hosted vs. GitHub-hosted**: runner group name
- **SKU family**: Actions / Packages / LFS / Copilot / Codespaces / Shared Storage

## Open-Source Tools

- **nektos/act** — https://github.com/nektos/act — MIT — 60K+ stars — runs GitHub Actions workflows locally via Docker. Not a cost tool, but enables pre-commit cost estimation by measuring what would run.
- **actions/toolkit** — https://github.com/actions/toolkit — MIT — official JS SDK — useful if building a custom Action that reports cost to PR.
- **actions-runner-controller (ARC)** — https://github.com/actions/actions-runner-controller — Apache-2.0 — Kubernetes-native self-hosted runners. The standard way to run on your own infra; shifts cost to K8s / EC2.
- **self-hosted-runner-cost-calculator** — community project, small stars count, calculates EC2 break-even vs. GitHub-hosted.
- **jitterbit/get-changed-files** and **dorny/paths-filter** — not cost tools directly, but path filtering on PRs is the #1 CI cost-reduction lever; worth surfacing as a Costly recommendation.
- **setup-buildx-action + actions/cache** — cache hit rate drives runner minute usage; measure hit rate and surface low-hit workflows.
- **gha-runner-scale-set** (Microsoft Azure) — autoscaling runners on AKS.
- **philips-labs/terraform-aws-github-runner** — https://github.com/philips-labs/terraform-aws-github-runner — self-hosted autoscaling on EC2 spot.
- **cli/cli (gh)** — https://github.com/cli/cli — `gh run list`, `gh workflow view` — useful for scripted cost audits.
- **GitHub Actions Importer** — https://github.com/github/gh-actions-importer — GitHub's official tool to migrate from Jenkins/CircleCI/TravisCI; useful context for sales conversations.
- **sanathkr/go-npm** and similar "post PR comment with cost" actions — small community projects that comment estimated cost on each PR.

No mature OSS GitHub Actions cost dashboard exists yet. Vantage and CloudZero have closed-source integrations. This is a clear wedge for Costly.

## How Competitors Handle These

- **Vantage** (https://www.vantage.sh/docs/github-actions-integration) — org-level auth via GitHub App, pulls Enhanced Billing API daily, normalizes into their unified "Services" taxonomy. UI shows per-repo, per-workflow, per-SKU spend with anomaly detection. No per-runner-size breakdown surfaced. Enterprise pricing.
- **CloudZero** (https://www.cloudzero.com/) — "Ingestion" module with a GitHub Actions source; allocates to CostFormation "entities" (teams, products). Strong on unit economics ("$/deploy").
- **Datadog CI Visibility** (https://docs.datadoghq.com/continuous_integration/) — focuses on test/flake/duration, not dollars. Integrates with GitHub Actions via webhook. Adjacent, not direct competitor.
- **Argonaut / Firefly** — cloud-cost focused; minor CI/CD coverage.
- **Cast AI** — Kubernetes cost focused; relevant if self-hosted runners live on K8s.
- **Spacelift Cost Estimation** (https://spacelift.io/) — IaC/cloud cost focused; Terraform-runs are the metered dimension. Tangential.
- **Harness Cloud Cost Management (CCM)** — https://www.harness.io/products/cloud-cost — has a "Build Cost" feature for their own CI, plus GitHub Actions integration. Emphasis is on "cost per pipeline" and anomaly alerts.
- **Atlassian Open DevOps / Jira** — no cost side directly; Compass has basic component-level cost via AWS tagging.
- **Backstage "CI Insights" plugin** — OSS, surfaces run duration & flakiness, no cost.
- **GitHub itself** — Billing → Usage UI shows per-product breakdown but lacks workflow-level attribution in the UI; enterprise export is CSV-only.

Costly's opportunity: best-in-class OSS that surfaces **per-workflow** and **per-runner-size** spend with cost-saving recommendations (cache hit rate, matrix reduction, self-hosted break-even, macOS→Linux migration).

## Books / Published Material

- **"Cloud FinOps" 2nd edition (Storment & Fuller, O'Reilly 2023)** — chapter on CI/CD cost allocation and showback patterns; FinOps Foundation-aligned.
- **"Continuous Delivery" (Humble & Farley, 2010)** — not cost-focused but defines the pipeline concepts Costly meters.
- **"Accelerate" (Forsgren, Humble, Kim 2018)** — DORA metrics; pipeline duration is a proxy for Lead Time.
- **GitHub's official "About billing for GitHub Actions"** — https://docs.github.com/en/billing
- **FinOps Foundation CI/CD capability** — https://www.finops.org/framework/capabilities/ — "Allocation" and "Reporting" capabilities explicitly cover CI cost.
- **Grafana's "How we reduced our GitHub Actions bill"** blog — real case study with cache-key and matrix-strategy tactics.
- **Shopify engineering blog** — multiple posts on self-hosted runner cost optimization.
- **GitHub's "Optimizing Your GitHub Actions workflow"** — official optimization guide.
- **"Effective DevOps" (Davis & Daniels, O'Reilly)** — culture/process framing, supports cost-as-a-first-class-metric.

## Vendor Documentation Crawl

Key pages pulled during this research run:

- https://docs.github.com/en/billing/concepts/product-billing/github-actions — product billing concepts, multipliers, minute consumption
- https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions — billing management, spending limits
- https://docs.github.com/en/rest/billing/enhanced-billing — the target API for v2 connector
- https://docs.github.com/en/rest/billing/billing — legacy per-product billing endpoints
- https://docs.github.com/en/rest/actions/workflow-runs — runs list + `created` filter
- https://docs.github.com/en/rest/actions/workflow-jobs — job-level runner labels
- https://docs.github.com/en/rest/actions/workflows#get-workflow-usage — aggregate per-workflow timing
- https://docs.github.com/en/actions/using-github-hosted-runners/about-larger-runners — large runner SKU ladder
- https://github.com/pricing — canonical plan comparison
- https://docs.github.com/en/rest/overview/resources-in-the-rest-api#rate-limiting — primary/secondary rate limit docs
- https://docs.github.com/en/webhooks-and-events/webhooks/webhook-events-and-payloads#workflow_run — webhook payload shape

## Best Practices (synthesized)

1. **Prefer Enhanced Billing API** for org/enterprise accounts — single call, itemized, covers all products.
2. **Always include `repository.private`** — skip public-repo runs when aggregating (they're $0).
3. **Cache `/timing` responses**: run_id is immutable, timing never changes post-completion. 30-day TTL, content-addressed.
4. **Map SKU → rate lookup table** maintained as config, not code constants — pricing changes every 18-24 months.
5. **Use webhooks for real-time**, backfill with REST for first-90-days.
6. **Expose per-workflow delta** week-over-week — largest cost saver surfaced prominently.
7. **Recommend self-hosted threshold**: breakeven at ~5K Linux minutes/month per 2-core runner (EC2 t3.medium spot).
8. **Filter `dependabot[bot]` and `github-actions[bot]`** into a separate bucket — often 20-30% of run count but shouldn't land on a human cost center.
9. **Matrix explosion alert**: `strategy.matrix` with > 10 combinations + long job → top cost-saver recommendation.
10. **Cache hit rate**: correlate `actions/cache` usage with run duration; low hit-rate = high cost.
11. **Minute-rounding**: bill in whole minutes per-job per the Docs — a 6-second job is 1 billable minute.
12. **Separate Packages/LFS storage cost** from compute — they show as different `product` rows in enhanced API and are often forgotten.

## Costly's Current Connector Status

File: `backend/app/services/connectors/github_connector.py`

- **Class**: `GitHubConnector(BaseConnector)` with `platform = "github"`
- **Auth**: PAT in `credentials["token"]`; optional `org`, `repos` list
- **Connection test**: GET `/user` — generic, works for both PAT and fine-grained
- **Primary fetch**: `_fetch_org_billing` calls the **legacy** `/orgs/{org}/settings/billing/actions` endpoint
- **Fallback**: per-repo `_fetch_repo_actions` → lists runs → per-run `_get_run_timing` call → aggregates by day+workflow
- **Pricing table**: hard-coded `RUNNER_PRICING = {"ubuntu": 0.008, "windows": 0.016, "macos": 0.08}`
- **Category**: `CostCategory.ci_cd`
- **Known issues**:
  - Uses deprecated endpoint; must migrate to Enhanced Billing API before the EOL window
  - Hard-codes Linux rate for ALL OS types in fallback mode (line 169: `cost = round(minutes * RUNNER_PRICING["ubuntu"], 4)` regardless of OS)
  - No support for large-runner SKUs (4/8/16/32/64-core) — under-counts spend for enterprise customers
  - Fires `/timing` per run (rate limit risk at >1K runs)
  - Ignores Packages, LFS, Copilot, Codespaces, Advanced Security
  - No webhook ingestion path
  - No grouping by actor, event, or branch
  - Silent `except Exception: pass` swallows errors — bad for debuggability

## Gaps

1. Migrate to Enhanced Billing Platform API (`/organizations/{org}/settings/billing/usage`)
2. Add large-runner SKU table (4/8/16/32/64-core + GPU) with per-SKU rates
3. Fallback-mode OS detection: use runner labels from `/runs/{id}/jobs`, not just file path
4. Add Packages / LFS / Copilot / Codespaces / Advanced Security cost ingestion (same endpoint, different `product` filter)
5. Webhook receiver endpoint for real-time run ingestion (reduces polling)
6. Actor and event breakdown (dependabot bucket, scheduled-vs-PR bucket)
7. Cache hit-rate signal surfaced (for "wasted minutes" recommendation)
8. Spending-limit read (separate API) so we can alert when an org is within 10% of its cap
9. Self-hosted runner detection — set `cost_usd=0` but still surface `usage_quantity` so customers see the real minute consumption
10. Multi-org / enterprise support — today we only loop one org

## Roadmap

- **Phase 1 (next sprint)**: swap legacy call for enhanced API; keep legacy as fallback; add large-runner SKUs to pricing map
- **Phase 2**: add Packages/LFS/Copilot/Codespaces product ingestion (same API, different `product`) — unlocks GitHub as a multi-SKU connector
- **Phase 3**: webhook receiver for real-time updates; `workflow_run` + `workflow_job` events
- **Phase 4**: actor/event/branch dimensions + matrix-explosion recommendation
- **Phase 5**: self-hosted runner cost attribution via AWS/GCP/Azure connector join on instance tags
- **Phase 6**: break-even calculator (self-hosted vs. GitHub-hosted) as a first-class Recommendation card
- **Phase 7**: Copilot ROI dashboard (per-user seat cost vs. PR velocity gain)

## Change Log

- 2026-04-24: Initial knowledge-base created
