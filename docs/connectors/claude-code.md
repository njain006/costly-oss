# Claude Code — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

Claude Code is Anthropic's official CLI (and VS Code / JetBrains extension) for agentic
coding, billed either via the Anthropic API (metered, Admin API visible) or via
Claude Pro / Max subscription seats (flat-rate, invisible to the Admin API).
Costly's new `claude_code_connector.py` parses the local JSONL transcripts under
`~/.claude/projects/**/*.jsonl` and emits cache-tier-aware `UnifiedCost` records
with project (cwd) attribution. Current grade: **B** — we match ccusage's core
math, but we are missing session/5-hour-block analytics, rate-limit quota
tracking, and multi-machine aggregation (the ccusage/agentsview frontier).

## Pricing Model (from vendor)

Claude Code consumes Anthropic's Messages API, so the effective pricing is
exactly the Anthropic model pricing plus Claude Code-specific multipliers for
cache behaviour. Transcripts rarely carry `service_tier` other than `"standard"`.

List price per million tokens (USD, list / non-batch, standard tier) as of
2026-04 — canonical source is the Anthropic pricing page
(<https://platform.claude.com/docs/en/about-claude/pricing>):

| Model family | Input | Output | Cache read (0.1×) | Cache write 5m (1.25×) | Cache write 1h (2.0×) |
|---|---|---|---|---|---|
| Claude Opus 4.7 / 4.6 / 4 | $15.00 | $75.00 | $1.50 | $18.75 | $30.00 |
| Claude Sonnet 4.7 / 4.6 / 4.5 / 4 | $3.00 | $15.00 | $0.30 | $3.75 | $6.00 |
| Claude Haiku 4.5 / 4 | $1.00 | $5.00 | $0.10 | $1.25 | $2.00 |
| Claude Haiku 3.5 | $0.80 | $4.00 | $0.08 | $1.00 | $1.60 |
| Claude Haiku 3 | $0.25 | $1.25 | $0.025 | $0.3125 | $0.50 |

Some secondary observations worth recording:

- **Opus 4.7 tokenizer uplift** — metacto.com and evolink.ai both report that
  Opus 4.7 (released 2026-04-16) tokenises inputs roughly 1.0–1.35× denser
  than Opus 4.6 at the same character count, effectively raising per-request
  cost even at the same headline rates. Source:
  <https://evolink.ai/blog/claude-api-pricing-guide-2026>.
- **Cache write 1h ttl** — Anthropic supports a 1-hour ephemeral cache in
  addition to the default 5-minute cache. 1h write is billed at 2.0× input,
  and reads are still 0.1× input. Source:
  <https://platform.claude.com/docs/en/build-with-claude/prompt-caching>.
- **Batch API** — 50% discount on both input and output for async jobs.
  Claude Code itself does not use Batch API (real-time agent loop), so cost
  tracking does not need to consider it for _this_ connector.
- **Priority tier** — `service_tier: "priority"` is a capacity-reservation
  tier (higher base price, guaranteed throughput). Emitted via the Messages
  API `service_tier` parameter. Claude Code transcripts leave this at
  `"standard"` by default. Source:
  <https://docs.anthropic.com/en/api/service-tiers>.
- **Subscription vs metered** — Claude Max ($100/mo or $200/mo) and Claude Pro
  ($20/mo) bundle Claude Code usage against a weekly + 5-hour rolling quota;
  metered API usage bills against the Anthropic account directly. Transcripts
  contain the same `usage` fields either way, but the metered path also
  appears in the Admin API, while subscription traffic does NOT — the
  connector is the only way to recover subscription cost.

## Billing / Usage Data Sources

### Primary

**Local JSONL transcripts under `~/.claude/projects/<slug>/<session-uuid>.jsonl`.**
Each assistant turn emits a row like:

```json
{
  "type": "assistant",
  "timestamp": "2026-03-25T22:46:46.454Z",
  "sessionId": "uuid",
  "cwd": "/abs/path/to/project",
  "gitBranch": "main",
  "message": {
    "model": "claude-opus-4-6",
    "usage": {
      "input_tokens": 3,
      "output_tokens": 512,
      "cache_read_input_tokens": 0,
      "cache_creation_input_tokens": 39655,
      "cache_creation": {
        "ephemeral_5m_input_tokens": 0,
        "ephemeral_1h_input_tokens": 39655
      },
      "service_tier": "standard"
    }
  }
}
```

- **Auth**: filesystem access to the user's home directory. No API key needed.
- **Rate limits**: none — this is local file I/O.
- **Write cadence**: Claude Code flushes one row per assistant turn; an
  interrupted session still leaves a valid, parseable JSONL.

### Secondary / Fallback

- **Anthropic Admin API** (`/v1/organizations/usage_report/messages` +
  `/v1/organizations/cost_report`) — covers metered Claude Code traffic under
  the same API keys an organisation uses for its own Messages-API apps.
  See `anthropic.md` for the full schema. This source DOES NOT see
  subscription-backed traffic.
- **OpenTelemetry metrics** — Claude Code can export OTEL metrics when
  `CLAUDE_CODE_ENABLE_TELEMETRY=1` is set. Recommended exporters: OTLP (to
  any OpenTelemetry collector), Prometheus, Honeycomb, Datadog. This is the
  officially supported fleet-wide aggregation path.
  Source: <https://github.com/anthropics/claude-code-monitoring-guide>.
- **Bedrock / Vertex-hosted Claude** — if the org runs Claude Code against
  Bedrock or Vertex AI (`ANTHROPIC_BEDROCK_BASE_URL` / `CLAUDE_CODE_USE_VERTEX`),
  the JSONL still records usage, but the billing lives in AWS CUR or GCP
  BigQuery billing export, respectively. Costly's `aws_connector.py` and
  `gemini_connector.py` pick that up.

### Gotchas

- **`cache_creation_input_tokens` vs nested `cache_creation.ephemeral_*`** —
  older Claude Code builds only emit the flat field; newer builds emit both.
  The connector treats a missing nested object as a full 5-minute write. If
  the user is on extended 1h cache ttl, only the nested form distinguishes.
- **`sessionId` resumes** — Claude Code `--continue` re-uses the same session
  UUID; `/clear` starts a fresh file. Aggregation by `(day, project, model)`
  glosses over this, which is fine for cost but wrong for "how many
  conversations did I have today" — see Roadmap.
- **`cwd` can be empty** for migrated pre-`cwd` transcripts; the connector
  falls back to Claude Code's directory-name-as-slug (`-Users-jain-src-...`).
- **Machine scope** — transcripts live on a single machine. Multi-device
  users need rsync, a fleet collector (OTEL), or agentsview's DB merge.
- **Deduping** — Anthropic retries often re-emit the same `requestId`;
  CCMeter and ccusage dedupe on it. Our connector currently does NOT.
- **Non-Anthropic models via proxy** — users running Claude Code pointed at
  a non-Anthropic endpoint (Kimi, OpenClaw, OpenRouter) still get JSONLs.
  The model string will be honest; cost estimation may silently fall back to
  Sonnet list prices if the prefix doesn't match. This is tracked in Gaps.
- **User prompts and tool results** leave no token footprint in JSONL —
  Anthropic's server-side tokenisation is the only authoritative count.
  Small drift (≤1%) relative to Admin API totals is normal.

## Schema / Fields Available

Per-turn fields emitted by Claude Code (2026-04 build):

| JSONL field | Type | Meaning |
|---|---|---|
| `type` | str | `"user"`, `"assistant"`, `"system"`, `"tool_use"`, `"tool_result"`, etc. Only `"assistant"` rows carry token usage. |
| `timestamp` | ISO-8601 str | UTC timestamp of the turn. |
| `sessionId` | uuid | Session identifier (stable across `--continue`). |
| `cwd` | abs path | Working directory when the turn was issued. |
| `gitBranch` | str | Branch at turn time (null if not a git repo). |
| `message.model` | str | Full model string (e.g. `claude-opus-4-6`, `claude-opus-4-7[1m]`). |
| `message.usage.input_tokens` | int | Non-cached input tokens billed at standard input rate. |
| `message.usage.output_tokens` | int | Generated output tokens (including thinking tokens when extended thinking is on). |
| `message.usage.cache_read_input_tokens` | int | Cached tokens read at 0.1× input rate. |
| `message.usage.cache_creation_input_tokens` | int | Total cache-write tokens (flat field). |
| `message.usage.cache_creation.ephemeral_5m_input_tokens` | int | Cache writes charged at 1.25× input. |
| `message.usage.cache_creation.ephemeral_1h_input_tokens` | int | Cache writes charged at 2.0× input. |
| `message.usage.service_tier` | enum | `"standard"` (default) / `"priority"` / `"batch"`. |
| `message.stop_reason` | str | `"end_turn"`, `"tool_use"`, `"max_tokens"`, etc. |
| `requestId` | str | Server-side request id — used for dedup across retries. |
| `parentUuid` | str | Links a turn to the request that triggered it (user or subagent). |

Per-file (session) fields worth surfacing:

- Session start / end timestamps (min/max `timestamp`).
- Session duration.
- Count of assistant turns.
- Count of tool calls (`tool_use` rows).
- Total cost.
- Branch / cwd.

## Grouping Dimensions

Costly's current connector aggregates by `(date_utc, project, model)` and writes
one `UnifiedCost` per bucket with:

- `platform = "claude_code"`
- `service = "claude_code"`
- `resource = <model>`
- `category = CostCategory.ai_inference`
- `team = <project>` (derived from cwd basename)
- `metadata.model`, `.project`, `.cwd`, `.input_tokens`, `.output_tokens`,
  `.cache_read_tokens`, `.cache_write_5m_tokens`, `.cache_write_1h_tokens`.

Dimensions we _could_ surface but don't yet:

- `gitBranch` — cost per branch (useful for feature-branch billing).
- `sessionId` — cost per conversation.
- 5-hour rolling block — matches Anthropic's quota accounting.
- Tool-call category (Bash / Edit / Read / WebFetch / Skill / Agent) — useful
  for "which tool is burning my quota".
- Subagent attribution (`parentUuid` chain) — root vs delegated work.
- Machine / hostname (multi-device).
- Extended-thinking share (thinking tokens vs non-thinking output).

## Open-Source Tools Tracking This Platform

The Claude Code ecosystem is unusually rich. Every tool listed below parses the
same `~/.claude/projects/**/*.jsonl` transcripts the connector uses; differences
are in cost model, visualisation, and aggregation scope.

| Tool | URL | Approx stars | Lang | License | What it tracks | Source | Notable |
|---|---|---|---|---|---|---|---|
| **ccusage** | <https://github.com/ryoppippi/ccusage> | ~5k | TypeScript | MIT | Daily/monthly/session/block cost + tokens | Local JSONL | De-facto standard; `npx ccusage@latest`; MCP server; offline pricing; VS Code companion. Site: <https://ccusage.com>. |
| **agentsview** (Wes McKinney) | <https://github.com/wesm/agentsview> | ~2k (recent) | Rust + TS | MIT | Sessions, tokens, cost across 20 AI coding agents (Claude Code, Codex, Cursor, Gemini, Copilot, OpenHands, etc.) | Local JSONL synced to SQLite | 100× faster than ccusage thanks to SQLite indexing; desktop bundle. Site: <https://www.agentsview.io>. |
| **sniffly** (Chip Huyen) | <https://github.com/chiphuyen/sniffly> | ~1.5k | Python | MIT | Usage stats, error analysis, tool-call breakdown, sharable reports | Local JSONL | Focus on error patterns ("Content Not Found" is 20–30% of errors). Launched July 2025. Site: <https://sniffly.dev>. |
| **Claude-Code-Usage-Monitor** (Maciek) | <https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor> | ~4k | Python | MIT | Real-time terminal monitor, burn-rate predictions, ML-based session-limit forecasting | Local JSONL | Focus on quota/rate-limit exhaustion warnings. |
| **claude-code-otel** (Cole Murray) | <https://github.com/ColeMurray/claude-code-otel> | ~300 | TS + Helm | MIT | OTEL metrics pipeline → Prometheus + Grafana | OTEL (`CLAUDE_CODE_ENABLE_TELEMETRY`) | Production-grade fleet observability reference impl. |
| **anthropics/claude-code-monitoring-guide** | <https://github.com/anthropics/claude-code-monitoring-guide> | ~1k | Markdown + configs | Apache-2.0 | Official walkthrough: Prometheus + OTEL, cost, productivity, ROI | OTEL | The vendor's canonical observability recipe. |
| **ccseva** (macOS menu bar) | <https://github.com/Iamshankhadeep/ccseva> | ~1.5k | TS (Electron) | MIT | Live token + quota menubar widget | Local JSONL (via ccusage) | Cross-platform fork: <https://github.com/digitaladaption/ccseva-windows>. |
| **lumo** | <https://github.com/zhnd/lumo> | ~400 | Rust + TS (Tauri) | MIT | Desktop dashboard: cost trends, token breakdown, heatmaps | Local daemon + SQLite | Local-first with native Tauri app. |
| **cc-wrapped** | <https://github.com/LenSin3/cc-wrapped> | ~200 | TS | MIT | Spotify-Wrapped-style year-in-review (git + Claude Code) | Local JSONL + git log | Part of a broader "wrapped" genre — see also miguelrios/2025-compiled, isaadgulzar/year-in-code, The-Money-Company-Limited/claudecodewrapped, lpcode808/Wrapped-Claude-Code, yurukusa/cc-toolkit. |
| **par_cc_usage** (Paul Robello) | <https://github.com/paulrobello/par_cc_usage> | ~200 | Python | MIT | Real-time monitor, 5-hour unified billing block, LiteLLM pricing | Local JSONL | PyPI: `par-cc-usage`; CLI: `pccu`. |
| **claude-code-usage-bar** | <https://github.com/leeguooooo/claude-code-usage-bar> | ~200 | Shell + TS | MIT | Single-line Claude Code `statusLine` with 5h + 7d quota bars and context window usage | Local JSONL + rate-limit API | Inline ASCII pet because why not. |
| **claude-meter** (abhishekray07) | <https://github.com/abhishekray07/claude-meter> | ~300 | Python | MIT | Local research proxy that intercepts OAuth tokens and decodes the hidden quota system | Proxy + token introspection | Research-grade; surfaces 5-hour + 7-day budget gauges not in JSONL. |
| **CCMeter** (hmenzagh) | <https://github.com/hmenzagh/CCMeter> | ~300 | Rust | MIT | Deep analytics + session insights; parallel JSONL parsing via rayon; OAuth rate-limit polling; dedup by `requestId` | Local JSONL + OAuth creds | Fastest parser; best dedup logic. |
| **philipp-spiess/claude-code-costs** | <https://github.com/philipp-spiess/claude-code-costs> | ~200 | TS | MIT | Interactive cost visualisation per conversation | Local JSONL | Companion to claude-code-viewer (upload transcripts to the web). |
| **ClaudeMeter** (puq-ai) | <https://github.com/puq-ai/claude-meter> | ~150 | Swift | MIT | macOS menu bar app: 5h + 7d usage + Opus-specific consumption | Local JSONL + rate-limit API | Native Swift; Sonoma+. |
| **ClaudeUsageTracker** (masorange) | <https://github.com/masorange/ClaudeUsageTracker> | ~150 | Swift | MIT | macOS menubar with accurate cost calculations | Local JSONL | Swift-native alternative. |
| **Claude-Usage-Tracker** (hamed-elfayome) | <https://github.com/hamed-elfayome/Claude-Usage-Tracker> | ~120 | Swift | MIT | Another SwiftUI menubar app for Claude usage limits | Local JSONL | Session windows, weekly limit focus. |
| **phuryn/claude-usage** | <https://github.com/phuryn/claude-usage> | ~300 | TS | MIT | Local dashboard with Pro/Max progress bar | Local JSONL | Web UI, session history. |
| **claude-code-usage-analyzer** (aarora79) | <https://github.com/aarora79/claude-code-usage-analyzer> | ~100 | Python | MIT | Cost + token breakdown by model and token type | ccusage CLI + LiteLLM pricing | Analysis-oriented; Jupyter-friendly. |
| **claude_telemetry** (TechNickAI) | <https://github.com/TechNickAI/claude_telemetry> | ~200 | Python | MIT | OpenTelemetry wrapper CLI (`claudia`) — exports to Logfire, Sentry, Honeycomb, Datadog | CLI interceptor | Drop-in `claude` → `claudia`. |
| **tokscale** (junhoyeo) | <https://github.com/junhoyeo/tokscale> | ~800 | TS + Rust TUI | MIT | Multi-agent: Claude Code, Codex, Cursor, Gemini, Kimi, OpenClaw, AmpCode, Pi, Factory Droid, etc. | Local tool-specific storage | Kardashev-scale leaderboard + 3D contributions graph. |
| **TokenTracker** (mm7894215) | <https://github.com/mm7894215/TokenTracker> | ~400 | TS (Electron) | MIT | Dashboard + macOS menubar + 4 widgets across Claude/Codex/Cursor/Gemini/Kiro/OpenCode/OpenClaw | Local storage | Zero-config multi-agent. |
| **coding_agent_usage_tracker** (Dicklesworthstone) | <https://github.com/Dicklesworthstone/coding_agent_usage_tracker> | ~200 | Python | MIT | Single CLI across Codex, Claude, Gemini, Cursor, Copilot | Mixed per-agent sources | Quota + cost unified view. |
| **ClaudeCodeStatusLine** (daniel3303) | <https://github.com/daniel3303/ClaudeCodeStatusLine> | ~200 | Shell | MIT | Status-line renderer: model, tokens, rate limits, git | Local JSONL | Customisable. |
| **ccstatusline** (sirmalloc) | <https://github.com/sirmalloc/ccstatusline> | ~500 | TS | MIT | Powerline-styled status line | Local JSONL | Themes. |
| **claude-code-viewer** / **claude-code-app** (philipp-spiess) | <https://github.com/philipp-spiess/claude-code-viewer>, <https://github.com/philipp-spiess/claude-code-app> | ~150 combined | TS | MIT | Web viewer for uploaded transcripts | Upload | Useful for sharing. |
| **Claude-Usage-Extension** (lugia19) | <https://github.com/lugia19/Claude-Usage-Extension> | ~400 | JS | MIT | Browser extension for claude.ai usage | DOM scraping | Tracks the _web app_, not CLI. |
| **cc-viewer** (weiesky) | <https://github.com/weiesky/cc-viewer> | ~150 | TS | MIT | Request-level monitoring proxy | HTTP interceptor | Debug-focused. |
| **LiteLLM model prices** | <https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json> | 19k+ (parent repo) | JSON | MIT | Central source-of-truth pricing table | Manual PRs | Most OSS Claude Code tools import this for cost math. |
| **awesome-claude-code** (hesreallyhim) | <https://github.com/hesreallyhim/awesome-claude-code> | ~8k | Markdown | CC0 | Curated list of all Claude Code tooling | N/A | Discovery / meta. |
| **jqueryscript/awesome-claude-code** | <https://github.com/jqueryscript/awesome-claude-code> | ~2k | Markdown | CC0 | Parallel curated list | N/A | Different curation perspective. |

Takeaway: the ecosystem has converged on _reading the JSONLs locally_ with LiteLLM
pricing. Differentiation is happening at (a) multi-agent aggregation
(agentsview, tokscale, TokenTracker), (b) rate-limit / quota introspection
(claude-meter, CCMeter, ClaudeMeter), and (c) analytics depth (sniffly's error
taxonomy, agentsview's heatmaps).

## How Competitors Handle This Platform

Claude Code is newer than Claude itself, so most cloud-cost platforms either
don't cover it yet or fold it into their Anthropic connector.

- **Vantage (vantage.sh)** — The "AI spend intelligence" product (`vantageaiops.com`)
  explicitly supports Claude Code, Codex CLI, and Gemini CLI. It captures
  tokens, cost, latency, quality scores; surfaces "cheaper-model" suggestions
  and context-compression hints (claims 20–40% savings). Free tier 10k
  requests/month, Team $99/mo for unlimited + cross-model pricing
  intelligence + team attribution. Of the competitors surveyed, Vantage has
  the most Claude-Code-specific product surface area.
  Source: <https://www.vantage.sh/blog/top-platforms-for-managing-ai-costs>.
- **CloudZero (cloudzero.com)** — Integrates with Anthropic Admin API and has
  an MCP server, but does not crack open Claude Code transcripts. For
  subscription-backed Claude Code traffic, CloudZero is blind.
  Source: <https://docs.cloudzero.com/docs/connections-anthropic>.
- **Finout (finout.io)** — Ingests Anthropic invoices (MegaBill) + Admin API.
  No Claude-Code-specific view. Finout's blog catalogues the ecosystem but
  doesn't parse transcripts.
  Source: <https://www.finout.io/blog/5-open-source-tools-to-control-your-ai-api-costs-at-the-code-level>.
- **Datadog CCM + LLM Observability** — Supports Claude cost tracking via
  Anthropic Admin API integration (launched 2025). Has OTEL support that
  Claude Code can export into via `CLAUDE_CODE_ENABLE_TELEMETRY`, so a
  self-hosted path exists, but the vendor does not ship a turnkey Claude Code
  dashboard. Source:
  <https://www.datadoghq.com/blog/anthropic-usage-and-costs/>.
- **DX (getdx.com)** — A developer-productivity platform; they expose a
  Claude Code connector that pulls Anthropic Console cost+usage. Not a
  general FinOps play. Source: <https://docs.getdx.com/connectors/claude-code/>.
- **Honeycomb** — Anthropic Usage and Cost monitoring integration exists;
  focuses on tracing rather than Claude-Code-subscription.
  Source: <https://docs.honeycomb.io/integrations/anthropic-usage-monitoring>.
- **Revefi (revefi.com)** — Warehouse-first (Snowflake, Databricks, BigQuery,
  Redshift). Recent blog posts mention LLM cost observability at a high
  level but no Claude Code specifics.
- **Select.dev, Keebo, Espresso AI, Chaos Genius/Flexera** — Warehouse-only
  (Snowflake). Not applicable to Claude Code.
- **Amberflo, Cloudchipr** — Generic billing/metering; no Claude Code
  specifics.

**Competitive gap Costly can exploit**: the JSONL source is a goldmine that
almost no commercial FinOps tool touches. Vantage AIOps is the only real
competitor on the LLM-CLI axis, and they're a separate product from the main
Vantage cloud-cost play. Costly can differentiate by unifying JSONL data with
the rest of the data-platform cost model (warehouse, BI, pipelines) — none of
the OSS tools do that, and none of the CloudZero/Finout-class FinOps tools
touch JSONL.

## Books / Published Material / FinOps Literature

Claude Code as a cost line item is too new for printed books. The relevant
canon is:

- **Cloud FinOps** (J.R. Storment & Mike Fuller, O'Reilly) — 2nd edition is
  the current shipping version; 3rd edition is in progress per FinOps
  Foundation community calls. Covers FinOps capabilities framework (Inform /
  Optimize / Operate) which applies directly to LLM spend.
  <https://www.oreilly.com/library/view/cloud-finops-2nd/9781492098348/>
- **FinOps Foundation — FinOps for AI Overview** (2025 whitepaper) — the
  canonical practitioner framework for LLM cost. Defines the "FinOps for AI"
  working group's position on model selection, backend infrastructure, and
  consumer-side optimizations.
  <https://www.finops.org/wg/finops-for-ai-overview/>
- **FinOps Foundation — AI Cost Estimation + How to Forecast AI** — sibling
  working-group papers.
  <https://www.finops.org/wg/effect-of-optimization-on-ai-forecasting/>
- **Anthropic — Claude Code Monitoring Guide** — the vendor's own Prometheus
  + OpenTelemetry recipe, including cost, productivity, and ROI sections.
  <https://github.com/anthropics/claude-code-monitoring-guide>
- **Anthropic — Manage costs effectively (Claude Code docs)** —
  <https://code.claude.com/docs/en/costs>
- **Finout blog series on AI FinOps** — the most prolific vendor blog:
  "OpenAI vs Anthropic API Pricing Comparison (2026)",
  "5 Open-Source Tools to Control Your AI API Costs",
  "FinOps in the Age of AI" (CPO guide).
  <https://www.finout.io/blog>
- **CloudZero blog** — "FinOps for Claude" and "CloudZero + LiteLLM" are
  practitioner-focused, if vendor-slanted.
  <https://www.cloudzero.com/blog/finops-for-claude/>
  <https://www.cloudzero.com/blog/cloudzero-litellm/>
- **Sniffly's launch post** (Chip Huyen) — one of the few honest public
  analyses of Claude Code usage patterns (Content-Not-Found errors dominate;
  grep/ls/glob are one-third of tool calls).
  <https://x.com/chipro/status/1945527700808184115>
- **Morph** — `anthropic-api-pricing` deep-dive by a coding-agent startup.
  <https://www.morphllm.com/anthropic-api-pricing>
- **Wes McKinney / agentsview launch** — no book, but McKinney's authority in
  the Python data space gives his commentary on agent observability
  disproportionate weight. <https://wesmckinney.com/software>
- **Hacker News discussions** — the launch threads for sniffly, agentsview,
  and ccusage are rich secondary sources:
  <https://news.ycombinator.com/item?id=45081711> (sniffly).

There is **no printed book specifically on Claude Code cost management** as of
2026-04. The FinOps Foundation AI working group is the closest to a recognised
standard.

## Vendor Documentation Crawl

- **Pricing** — <https://platform.claude.com/docs/en/about-claude/pricing>
  The canonical list-price table. Includes cache multipliers and batch
  discount.
- **Prompt caching** — <https://platform.claude.com/docs/en/build-with-claude/prompt-caching>
  5m / 1h ephemeral cache; TTL syntax; read / write pricing rules.
- **Service tiers** — <https://docs.anthropic.com/en/api/service-tiers>
  Covers `"standard"` / `"priority"` / `"batch"` response values and the
  `service_tier` request parameter (`"auto"` / `"standard_only"`).
- **Admin API overview** — <https://platform.claude.com/docs/en/build-with-claude/administration-api>
  Admin key concept, key rotation, workspace model.
- **Usage & Cost API** — <https://docs.anthropic.com/en/api/usage-cost-api>
  + <https://platform.claude.com/docs/en/build-with-claude/usage-cost-api>
  The authoritative Admin API reference for org-wide usage rollups.
- **Get Messages Usage Report** —
  <https://docs.anthropic.com/en/api/admin-api/usage-cost/get-messages-usage-report>
  Per-endpoint reference (parameters, pagination, rate limits).
- **Claude Code — Manage costs effectively** —
  <https://code.claude.com/docs/en/costs>
  Vendor-recommended practices: set budgets, use subscription when
  amortised > metered, prefer Sonnet for refactor/skim tasks.
- **Claude Code — OpenTelemetry / Telemetry** —
  <https://code.claude.com/docs/en/monitoring-usage>
  Env var: `CLAUDE_CODE_ENABLE_TELEMETRY=1`. Metric names:
  `claude_code.token_usage`, `claude_code.cost`, `claude_code.session_duration`.
  Known bug history: OTEL broke in 2.64, silently no-ops in 2.1.113 (see
  anthropics/claude-code issues #13803, #50567).
- **Claude Code — statusLine API** — <https://code.claude.com/docs/en/statusline>
  Scripts emit a single status line per render; used by several OSS tools.
- **Cost and Usage Reporting in Console (help center)** —
  <https://support.anthropic.com/en/articles/9534590-cost-and-usage-reporting-in-console>
- **Release notes / changelog** — Claude Code posts releases to GitHub
  Releases (<https://github.com/anthropics/claude-code/releases>). Cadence is
  multiple releases per week. Relevant changes since 2025:
  - 2.x introduced SQLite-backed session storage for faster resume.
  - 2.64 break/fix of OTEL exporters (see issues above).
  - Rolling addition of multi-model support (Bedrock, Vertex, custom OpenAI-compatible).
- **Region / data-residency** — Anthropic's `inference_geo` dimension on the
  Usage API lets orgs verify geographic routing.
- **SLA / compliance** — Anthropic publishes SOC2 Type II, HIPAA eligibility
  under BAA, GDPR DPA. Enterprise plan includes extended data-retention
  controls. Source: <https://trust.anthropic.com>.

## Best Practices (synthesized)

1. **Parse transcripts, not just the Admin API.** Subscription-backed Claude
   Code usage is invisible to the Admin API; without JSONL parsing you
   understate cost by whatever proportion of the org is on Pro/Max.
2. **Honor the four token classes separately** — `input`, `output`,
   `cache_read` (0.1×), `cache_write_5m` (1.25×), `cache_write_1h` (2.0×).
   Collapsing them into "tokens × rate" over-estimates by 2–10× on
   cache-heavy sessions.
3. **Use the LiteLLM pricing JSON as a pricing oracle** rather than
   hand-coded tables. Refresh nightly. LiteLLM lags Anthropic by ≤ 48h.
4. **Dedupe by `requestId`.** Retries are common under network wobble;
   CCMeter and ccusage both do this. We currently don't.
5. **Group by `cwd` basename** (project) for attribution — this is what
   every OSS tool does, and it matches how engineering leaders think.
   Also expose `gitBranch` as a drill-down.
6. **Add 5-hour rolling blocks** — they match Anthropic's subscription
   quota accounting. ccusage's `blocks` command is the reference.
7. **Flag the Opus 4.7 tokenizer uplift** to users when they have Opus 4.6
   history — same characters cost 1.0–1.35× more tokens under 4.7.
8. **Fall back to "Sonnet list price" on unknown models but warn loudly** —
   the fallback is fine for cost _estimate_ but hides the fact that the user
   is on a non-Anthropic model (Kimi, local, OpenRouter).
9. **Expose tool-call category** (Bash / Edit / Read / WebFetch / Skill /
   Agent) — agentsview and sniffly both prove this is the single most
   actionable dimension for developer coaching.
10. **Multi-machine aggregation** — rsync of `~/.claude/projects` to a central
    location (or OTEL exporter) is the only way to get fleet-wide truth.
    Offer a lightweight daemon that ships new rows to the Costly backend.

## Costly's Current Connector Status

**File:** `/Users/jain/src/personal/costly/backend/app/services/connectors/claude_code_connector.py`

The connector is ~320 lines, test-covered, and ships in the unified-costs map.
It does the following well:

- Parses every `~/.claude/projects/*/*.jsonl` file under the user's home dir
  (configurable via `credentials["projects_dir"]`).
- Emits a `TokenUsage` frozen dataclass with all five token classes
  (input / output / cache_read / cache_write_5m / cache_write_1h).
- Resolves pricing with longest-prefix match — Opus 4.7 and 4.6 resolve
  correctly before generic "opus-4".
- Falls back to Sonnet pricing on unknown models (safe default).
- Handles both the flat `cache_creation_input_tokens` field (legacy Claude
  Code builds) and the nested `cache_creation.ephemeral_*_input_tokens`
  fields (current builds).
- Aggregates per `(date_utc, project, model)` — correct granularity for
  a unified dashboard.
- Derives a human-readable project name from `cwd` with a fallback to the
  Claude-Code-encoded directory slug (`-Users-jain-src-foo` → `foo`).
- Survives malformed JSON lines and unreadable files (skips silently).
- Test-covered in `/Users/jain/src/personal/costly/backend/tests/test_claude_code_connector.py`.

Known limitations (see Gaps section for actionable items):

- No `requestId` dedup.
- Does not surface `sessionId`, `gitBranch`, or tool-call categories in
  `UnifiedCost.metadata`.
- Cost model covers Anthropic models only — users on proxied Kimi / local
  models get Sonnet-priced approximations with no warning.
- No 5-hour rolling-block analytics (ccusage's differentiator).
- Single-machine scope.
- No pricing refresh from LiteLLM.
- Opus 4.7 tokenizer uplift not acknowledged.

## Gaps Relative to Best Practice

1. **Dedup by `requestId`** — `O(n)` hash set, ~10 lines of code.
2. **Session-level aggregation** — expose `sessionId` as an additional metadata
   key; optionally produce one `UnifiedCost` per session for a drill-down view.
3. **5-hour rolling block bucketing** — match Anthropic subscription quota.
4. **Tool-call category breakdown** — parse `tool_use` rows, count by name
   (Bash, Edit, Read, WebFetch, Skill, Agent, Grep, Glob, Write, NotebookEdit,
   TodoWrite, Task, etc.), emit as metadata so the UI can pivot on it.
5. **`gitBranch` metadata** — cheap; unlocks "cost per feature branch".
6. **Thinking-token share** — distinguish visible output tokens from thinking
   tokens when extended thinking is on. Claude Code doesn't expose this
   separately in JSONL today, but subtracting `stop_reason="end_turn"`
   output from `stop_reason="tool_use"` output approximates it.
7. **Multi-user / multi-machine aggregation** — either a Costly-shipped
   daemon that ships new JSONL rows to the backend, or instructions for
   pointing `projects_dir` at a shared rsync target, or an OTEL-collector
   path for fleet scale.
8. **Pricing oracle** — nightly sync from LiteLLM model_prices_and_context_window.json
   with fallback to our built-in table if LiteLLM fetch fails.
9. **Opus 4.7 tokenizer warning** — surface a banner on projects that have
   >20% of tokens on 4.7 vs prior period's 4.6, because the same workflow
   will cost more.
10. **Non-Anthropic model warning** — when the model prefix doesn't match
    any known Anthropic model, emit a `metadata.unknown_model=true` flag
    and don't silently use Sonnet pricing.
11. **Subagent attribution** — `parentUuid` chain lets us label a turn as
    "user-initiated" vs "delegated to Task/Skill tool". Important for the
    agents-calling-agents era.
12. **Hostname / machine** — read `os.uname().nodename` and stash in
    metadata so the UI can pivot on it.
13. **Streaming backfill mode** — today we re-parse everything on each
    `fetch_costs(days=N)` call. With a watchpath daemon we could tail
    JSONLs and push only deltas, which matches ccusage's real-time mode.

## Roadmap

**Near-term (ship this week):**

- `requestId` dedup (≤ 10 lines; prevents double-counting retries).
- Expose `sessionId`, `gitBranch`, `hostname` in `metadata`.
- Flag unknown-model fallbacks loudly (`metadata.unknown_model=true`).
- LiteLLM pricing sync at connector init (with graceful fallback).

**Medium (next month):**

- 5-hour rolling-block analytics endpoint (`/api/claude-code/blocks`).
- Tool-call category breakdown.
- Subagent (`parentUuid`) attribution.
- Session drill-down view in the frontend.
- Alert: "you burned 80% of your 5-hour Max quota — back off or upgrade".
- Opus 4.7 tokenizer uplift banner.

**Long (quarter):**

- Multi-machine aggregation (Costly daemon + lightweight REST push).
- Tie JSONL data into warehouse costs in the unified dashboard ("you spent
  $12 asking Claude Code to write Snowflake SQL that then cost $47 to run").
- Skill / Agent usage heatmap — fills the "which skill earns its keep?" gap
  nobody else covers.
- Competitive lever: offer to ingest agentsview's SQLite DB so users already
  on agentsview can pivot their existing data inside Costly.

## Change Log

- 2026-04-24: Initial knowledge-base created by overnight research run.
