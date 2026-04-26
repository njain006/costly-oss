# Costly Dashboard — Visualization & UX Specification

**Status:** Draft v1.0
**Scope:** Dashboard pages of `costly.cdatainsights.com` (frontend-next/ app).
**Stack anchors:** Next.js 15 (App Router) + React 19 + Tailwind v4 + shadcn/ui + Recharts 3 + lucide-react. See `CLAUDE.md`.
**Audience:** Data engineers, platform engineers, AI-eng leads, and CTOs who want a single pane of glass over their data + AI platform spend, plus a conversational agent on top of it.

This spec is opinionated. Where a choice is made (e.g. stacked area over calendar heatmap for the hero chart), rationale is given. Every page section lists the Recharts/SVG artifacts, shadcn components, mobile breakpoints, dark-mode behavior, and WCAG AA notes.

---

## 0. Design Principles (global)

These apply to every page.

**Density with calm.** Linear-style density is the target, not Datadog-style overload ([linear.app](https://linear.app/)). Each page fits the hero narrative in the top third of the viewport; deep detail lives below the fold or in a drawer.

**Transparency over marketing.** Every cost number has a provenance tooltip: source API, fetched-at timestamp, and the pricing override (if any) applied. Inspired by Stripe Dashboard's per-transaction fee transparency.

**Every number is a link.** Clicking any KPI, bar segment, or table cell drills to the filtered view — no standalone "details" routes for users to guess. PostHog and Vercel Analytics do this well ([vercel.com/analytics](https://vercel.com/analytics)).

**AI-first but not AI-only.** The agent (chat) is always one keystroke away (`⌘K`), surfaced as a persistent pill on the Overview page and as a floating input elsewhere. But the dashboard must be fully usable without ever opening the chat.

**No chart without a takeaway.** Every chart has a one-line human-readable summary rendered above it (e.g. "Spend up 14% vs last week, driven by Snowflake `ANALYTICS_WH`"). The agent writes these; they fall back to a deterministic template.

**Design tokens.** Stick to the palette in `frontend-next/src/lib/constants.ts`:

```
primary:      #0C4A6E  (slate-900-ish deep blue)
primaryLight: #38BDF8
accent:       #0EA5E9
chart[]:      8-color categorical ramp
success:      #059669 / warning: #D97706 / danger: #DC2626
```

Keep Recharts grid stroke at `#f1f5f9` (already the convention in `dashboard/page.tsx`). All chart backgrounds white in light mode, `slate-900` in dark mode. Axis tick font size 11px.

**Motion.** Use `tw-animate-css` (already installed) for enter/exit only. No looping animations on charts — they read as noise in a cost dashboard.

---

## 1. Overview (landing dashboard after login)

### 1.1 Purpose

One glance answers: *Am I over budget? Did anything spike? What should I do next?*

Everything else is a click away. This page should be viewable in under 3 seconds on a 4G connection, so chart data is lazy-loaded after KPIs.

### 1.2 Hero KPIs (6 tiles)

```
┌─────────────┬─────────────┬─────────────┬─────────────┬─────────────┬─────────────┐
│ Month-to-date│ 7d Δ       │ Forecast    │ Budget      │ Cache savings│ Top risk    │
│ $12,847     │ +14.2% ↑   │ $18,420     │ 68% used    │ $1,310       │ 2 anomalies │
│ across 7    │ vs prior 7  │ by EOM      │ $1,580 left │ 42.8% hit    │ 1 budget    │
│ platforms   │             │ +9% MoM     │ 12d runway  │ rate         │             │
│ spark ▁▂▃▅▇ │ spark ▃▄▆▇▅ │ dotted line │ ━━━━━━─ 68% │ dial arc 43% │ ● ● ●       │
└─────────────┴─────────────┴─────────────┴─────────────┴─────────────┴─────────────┘
```

**Which 6?** After benchmarking Vantage, CloudZero, Select.dev, and Helicone, these are the numbers a data/AI team lead checks daily:

1. **Month-to-date spend** — anchor number. Shows total across connected platforms with a mini sparkline of the last 30 days.
2. **7-day delta** — "is something changing?" trend signal. `+14.2%` with colored arrow. Uses a 7d vs prior-7d window, not WoW, to smooth weekends.
3. **End-of-month forecast** — linear regression on MTD daily spend + seasonality factor (weekday vs weekend multipliers). Shows expected vs last-month actual.
4. **Budget status** — if any budget is set. Single-line progress bar with "days of runway at current burn." If no budget, this tile becomes a CTA to "Set a budget."
5. **Cache savings** — *costly's differentiator*. `$1,310 saved this month` + cache hit rate `42.8%`. This is the AI-cost hero metric that Vantage and CloudZero do not surface.
6. **Top risk** — count badge summarizing open anomalies + budget threshold breaches + near-exhaustion warnings. Clicking goes to Anomalies page pre-filtered.

**Why 6 not 4?** Data teams want compute + AI coverage in one glance. 4 would force a choice between "total spend" and "AI cache savings"; the latter is our wedge and must stay visible on cold start.

**Components:** `StatCard` (already exists at `frontend-next/src/components/stat-card.tsx`) extended with:
- `delta?: { value: number; direction: "up"|"down"|"flat" }`
- `sparkline?: number[]` (rendered as a 60x16 inline Recharts `<LineChart>` with no axes)
- `variant?: "default"|"warning"|"danger"|"success"` drives border-left color

**Mobile:** 6 tiles → 2 columns × 3 rows on <640px; 3 × 2 on `md`; 6 × 1 on `lg`. Existing `grid-cols-2 md:grid-cols-3 lg:grid-cols-6` convention matches.

### 1.3 Primary chart — stacked area by platform (hero)

```
┌─────────────────────────────────────────────────────────────────────┐
│ Daily spend by platform        [7D] [14D] [30D] [90D]   [Stacked ⌄]│
│ ▲ spike Mar 12: Snowflake +$240 ← agent annotation (click to chat) │
│                                                                     │
│ $700┤                                          ╱╲                   │
│     │                           ╱╲          ╱╱  ╲╲                │
│ $500┤                         ╱    ╲      ╱╱      ╲╲              │
│     │                ╱───╲   ╱      ╲    ╱╱        ╲              │
│ $300┤  ╱──╲    ╱───╱      ╲╱        ╲  ╱            ╲             │
│     │ ╱    ╲  ╱                      ╲╱              ╲            │
│   0 └───────────────────────────────────────────────────           │
│       Mar 01    Mar 08    Mar 15    Mar 22    Mar 29               │
│     ■ Snowflake  ■ AWS  ■ OpenAI  ■ Anthropic  ■ dbt ■ Others     │
└─────────────────────────────────────────────────────────────────────┘
```

**Choice: stacked area (default), toggleable to grouped line or calendar heatmap.**

Rationale:
- **Stacked area** answers "what's my total, and how is the mix moving?" in one frame. Most cost FinOps dashboards (Vantage, Finout) default to this because category-mix shift is the #1 question after total. It matches the existing `dashboard/page.tsx` pattern (compute + cloud_services stacked).
- **Grouped line (toggle)** is better when users are debugging a single platform spike — preserves the absolute line for each platform without stacking distortion. Toggle lives in a shadcn `Select` at top-right.
- **Calendar heatmap (toggle)** is best for detecting day-of-week patterns (e.g. "we always spike on dbt job day"). Not the default because it de-emphasizes the total. Custom SVG, one cell per day, 7×N grid, cell fill = cost intensity.

**Annotations.** Every detected anomaly (from `/api/anomalies`) renders as a Recharts `<ReferenceLine>` with a small labeled dot. Clicking a dot opens a side sheet with the anomaly detail (see §4). This mirrors the existing `ReferenceLine` annotation pattern in `dashboard/page.tsx` line 95.

**Components:** Recharts `<AreaChart>` with `stackId="1"` for all 6 platform series; ordered by month-to-date total (descending). `<Legend>` with click-to-toggle series. Date-range picker reuses existing `DateRangePicker` from `components/date-range-picker.tsx`.

**Color order.** Snowflake first (anchor customer), then AWS, then the AI trio (Anthropic / OpenAI / Gemini) as adjacent warm colors, then "Others" as neutral slate. Use `COLORS.chart[0..5]` + `slate-300` for Others.

**Mobile:** Collapse legend to 2-line scrollable chips; reduce X-axis ticks to 4 labels max; keep stacked area (it works well on narrow screens).

### 1.4 Secondary widgets (4-panel grid below hero chart)

```
┌───────────────────────────┬───────────────────────────┐
│ Top cost drivers (table)  │ Recommendations (top 3)   │
│ Snowflake ANALYTICS_WH … │ Resize OPS_XL → L   $340/mo│
│ AWS us-east-1 Redshift … │ Mute idle dbt env   $120/mo│
│ OpenAI gpt-4o-mini  …    │ Cache Anthropic sys $ 90/mo│
│                           │ [See all recs →]          │
├───────────────────────────┼───────────────────────────┤
│ Anomalies (timeline)      │ Cache-hit panel           │
│ ● Mar 12 Snowflake +140% │  Dial 42.8% + trend line  │
│ ● Mar 10 OpenAI +$230    │  $1,310 saved MTD         │
│ ○ Mar 08 AWS expected ✓  │  Would save $980 more if  │
│ [See all →]               │  hit rate → 70%           │
└───────────────────────────┴───────────────────────────┘
```

**Top cost drivers.** Flat shadcn `<Table>` — top 5 resources across all platforms with a micro `trend` column (▲14% / ▼3%) and sparkline. Click any row → platform deep-dive with that resource pre-filtered.

**Recommendations.** Top 3 by projected monthly savings; "See all" → Recommendations page. Each row shows effort-badge (Low/Med/High) and savings number.

**Anomalies timeline.** Vertical feed, last 14 days, with severity dots (red/amber/slate) and a relative timestamp. Muted anomalies shown greyed out. Inspired by Linear's activity feed density.

**Cache-hit panel.** See §2.2 for the full dial spec. On Overview this is a compact variant: one small SVG dial (64×64) + trend sparkline + "$ saved" counter.

**Components:** 2×2 grid of shadcn `<Card>` at `lg`; single column stack below.

### 1.5 Agent prompt entry point

Two surfaces:

1. **Persistent pill** anchored bottom-right on Overview (only). Background `bg-sky-500/10`, `Sparkles` icon, text "Ask Costly anything — ⌘K". Floats above content; z-40. Clicking pushes to `/chat`.
2. **Hero inline strip** — between KPIs and the primary chart:

```
┌─────────────────────────────────────────────────────────────────┐
│ ✨ "Why did OpenAI spend double this week?"  [Ask →]           │
│    "Which warehouse should I downsize?"                         │
│    "Show me dbt models costing >$100/month"                     │
└─────────────────────────────────────────────────────────────────┘
```

Three rotating suggested prompts (fade swap every 6s). The same suggestions exist in `chat/page.tsx` `SUGGESTIONS` array — reuse that module-level const so they stay in sync. Clicking any suggestion routes to `/chat?q=<encoded>` and auto-sends.

**Keyboard:** `⌘K` / `Ctrl+K` opens a command-menu overlay (shadcn `Dialog`) with the same suggestions, current page as context, and an input. Submit → `/chat?q=`.

### 1.6 Empty state (fresh install, zero connectors)

```
┌──────────────────────────────────────────────────────────────┐
│ Welcome to Costly.                                           │
│                                                              │
│ Connect your first platform to see real cost intelligence.   │
│                                                              │
│ [ Connect Snowflake ]  [ Connect AWS ]  [ Connect OpenAI ]  │
│                                                              │
│ Or → Try the demo (pre-populated fake data)                 │
│                                                              │
│ ┌──────────────────────────────────────────────────────┐    │
│ │   Sample dashboard preview (greyscale, non-clickable)│    │
│ └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

- Three primary connector CTAs — the most common starting points. Click routes to `/platforms` with the connector modal pre-opened.
- Secondary "Try the demo" link sets a session flag that triggers demo data (the `services/demo.py` path already exists).
- Below the fold: greyscale screenshot of the populated dashboard so users know what they're about to get.

**Dark mode:** Same layout, CTAs use `bg-sky-500` for contrast; greyscale screenshot stays greyscale (intentional de-emphasis).

### 1.7 Page-level a11y and layout

- Skip-to-content link above the sidebar.
- All KPI tiles are `<a>` or `<button>` — not static divs. Focus ring visible (Tailwind `focus-visible:ring-2 ring-sky-500`).
- Chart series colors pass WCAG AA against white (slate-50 background for cards also passes). The 8-color `COLORS.chart` ramp has already been tuned for this.
- Sparklines include `aria-label="Sparkline: cost trend, range $X to $Y"`.
- Page title: `<h1>Dashboard</h1>` — one per page, not per card.

---

## 2. AI Spend page (`/ai-costs`)

This is costly's hero feature. Three providers (Claude, OpenAI, Gemini) unified with shared token taxonomy. The backend connectors already normalize to a `UnifiedCost` record (see `backend/app/services/connectors/anthropic_connector.py`, `openai_connector.py`, `gemini_connector.py`); this page needs an extended shape that preserves tier-level tokens.

### 2.1 Page header

```
┌──────────────────────────────────────────────────────────────────┐
│ AI Spend Intelligence                                            │
│ Claude + OpenAI + Gemini combined · last synced 4 min ago       │
│                                            [7D] [30D] [90D] [YTD]│
├──────────────────────────────────────────────────────────────────┤
│ ┃Total $2,847 ┃Tokens 840M┃Cost/1k $0.0034┃Cache hit 43%┃      │
│ ┃MoM +9% ▲   ┃MoM −3% ▼ ┃MoM −12% ▼ ✓ ┃+5pp vs last mo┃      │
└──────────────────────────────────────────────────────────────────┘
```

Four KPIs: total spend, total tokens, blended $ per 1K tokens, cache hit rate. MoM deltas with direction indicators. `Cost/1k` going down is good (teal `down`); cache hit rate going up is good (teal `up`). Arrow color reflects desirability, not direction — important for cognitive load.

### 2.2 Cache-hit rate — dial + trend (both, side-by-side)

```
┌───────────────────────┬───────────────────────────────────────────┐
│    Cache hit rate     │ Rate over time                            │
│                       │ 70%┤                                      │
│      ╱─────╲          │    │              ╱───                    │
│     │ 42.8% │          │ 50%┤      ╱──────                        │
│      ╲─────╱          │    │    ╱                                 │
│   $1,310 saved MTD    │ 30%┤ ╱                                    │
│  Would save $980 more │    └──────────────────────────────────    │
│   if at 70% target    │     Mar 01   Mar 15   Mar 31              │
└───────────────────────┴───────────────────────────────────────────┘
```

**Choice: both — dial AND trend.**

Rationale:
- The dial gives an instant "where are we now" read and is the most scannable. Single arc 0–100% with a target marker at 70% (or user-configured). Custom SVG with a `<path>` arc; no Recharts gauge (Recharts doesn't ship a native gauge). 180° arc, stroke width 16, rounded caps. Fill color interpolates: red <30%, amber 30–60%, teal 60–80%, sky >80%.
- The trend line explains *how we got here* and reveals whether cache optimization work is paying off. Single Recharts `<LineChart>` with one `<Line>` for `cache_hit_rate`; y-axis 0–100%. Dashed reference line at target.
- Side-by-side is critical: alone, the dial is context-free; alone, the trend hides today's number.

**$ saved counter** is the ROI wedge. Computed as: `sum(cache_read_tokens × input_price) − sum(cache_read_tokens × cache_read_price)` per day, across all three providers. The "would save $980 more" counterfactual is computed assuming tokens re-routed to cache-read pricing.

**Components:** Two `<Card>` side-by-side; dial is a React component `<CacheDial value={0.428} target={0.7}/>` rendering inline SVG. Trend uses Recharts `<LineChart>` + `<ReferenceLine y={70} strokeDasharray="4 4" />`.

### 2.3 Token-tier breakdown — stacked area (with alluvial drill-down)

```
Stacked area (default):
┌──────────────────────────────────────────────────────────────────┐
│ Tokens by tier — 30 days                                         │
│ 40M┤                               ▓▓▓▓▓                         │
│    │              ▓▓▓▓▓▓▓▓▓     ▓▓▓▓▓▓▓▓    ← output            │
│ 30M┤           ▓▓▓▓▓▓▓▓▓▓▓▓▓  ▓▓▓▓▓▓▓▓▓▓▓    ← input             │
│    │        ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒   ← cache_write_1h    │
│ 20M┤     ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   ← cache_write_5m    │
│    │   ████████████████████████████████████ ← cache_read        │
│  0 └──────────────────────────────────────────                   │
│     Mar 01  Mar 08  Mar 15  Mar 22  Mar 29                       │
│     [View as $] [View as tokens]    [Switch to alluvial]         │
└──────────────────────────────────────────────────────────────────┘
```

**Choice: stacked area as default; alluvial/sankey as a secondary "flow" toggle.**

Rationale for rejecting alternatives:
- **Sunburst** — beautiful for a single snapshot but unreadable over time. Rejected.
- **Alluvial (sankey)** — excellent for the question *"how are tokens flowing from provider → model → tier?"* but overkill for the daily-trend question. Makes sense as a secondary view.
- **Stacked area** — wins as default because the top question is "is my cache-read share growing?" — a trend question. Five series: `cache_read`, `cache_write_5m`, `cache_write_1h`, `input`, `output`. Colors ordered cold→warm so cache tiers sit at the bottom (the cheapest, most-desirable tokens).

**Toggle "View as $" / "View as tokens"**: Same chart, different Y axis. Cost view reveals that 1M cache-read tokens ≠ 1M output tokens in $ terms — which is the whole point of this page.

**Alluvial flow (toggle).** Custom SVG or a lightweight library (no Recharts support). Recommend `d3-sankey` loaded dynamically. Flow: Provider (3 nodes) → Model (~8 nodes) → Tier (5 nodes). Band width = token count. Use this as a "weekly flow" snapshot, not a time series.

**Components:** Recharts `<AreaChart>` stacked; shadcn `<Tabs>` for the `$` / `tokens` toggle; a lazy-loaded `<SankeyFlow>` for alluvial. Data source extension needed: the existing `AiCostsData.daily_tokens` in `frontend-next/src/app/(dashboard)/ai-costs/page.tsx` only has `input | output | total`. Extend backend response to include `cache_read | cache_write_5m | cache_write_1h`.

### 2.4 Per-model breakdown — horizontal bar with mini-columns

```
┌──────────────────────────────────────────────────────────────────┐
│ By model — 30 days                      Sort: [Cost ⌄] [Tokens] │
│                                                                  │
│ claude-sonnet-4-20250514  ████████████████████ $1,240  210M tok │
│   43% cache ● 12% output     ↓ $0.0059/1k    MoM +12% ▲         │
│ gpt-4o-mini              ██████████ $620   420M tok           │
│   N/A cache ● 8% output      ↓ $0.0015/1k    MoM −4% ▼         │
│ gemini-2.5-pro           ███████ $480     85M tok             │
│   N/A cache ● 18% output     ↓ $0.0056/1k    MoM +20% ▲        │
│ claude-haiku-4-20250514  ████ $290         95M tok             │
│   28% cache ● 10% output     ↓ $0.0031/1k    MoM −8% ▼          │
│ claude-opus-4-20250514   ██ $217            4M tok             │
│   68% cache ● 22% output     ↓ $0.0542/1k    MoM +3%            │
└──────────────────────────────────────────────────────────────────┘
```

Horizontal bars, width proportional to cost. Each row has:
- model name + colored provider-dot on left
- bar (Recharts doesn't need to own this — pure Tailwind `div` with `width: X%` works and is faster)
- `$` and token totals
- inline micro-stats: cache %, output %, $/1k, MoM delta

Click a row → filters the rest of the page to that model (all charts update, page breadcrumb shows "Filtered: claude-sonnet-4").

**Why horizontal bars over pie/donut?** 5–15 models is too many for a readable pie. Horizontal bars scan linearly, support inline metadata, and sort naturally. CloudZero and Vantage both use this pattern.

### 2.5 Per-project / per-workspace attribution — treemap

```
┌──────────────────────────────────────────────────────────────────┐
│ By project — 30 days                         Group: [project ⌄] │
│ ┌─────────────────────────┬─────────────────┬─────────────────┐ │
│ │                         │                 │                 │ │
│ │    costly-oss           │   pangea-mvp    │  silai-prod    │ │
│ │    $890                 │   $440          │  $220           │ │
│ │                         │                 │                 │ │
│ │                         ├─────────┬───────┤  ┌──────┐       │ │
│ │                         │ rbc-prep│other  │  │other │       │ │
│ │                         │ $180    │$80    │  │$30   │       │ │
│ └─────────────────────────┴─────────┴───────┴──┴──────┘       │ │
└──────────────────────────────────────────────────────────────────┘
```

**Choice: treemap, with horizontal-bar as toggle.**

Rationale:
- Attribution is inherently hierarchical (workspace → project → model) and cost-weighted — treemap is the canonical visualization. Recharts supports `<Treemap>` out of the box.
- Horizontal bar is the fallback when projects >20 (treemap gets unreadable with tiny tiles).
- Toggle `Group: [project | workspace | user | tag]` uses metadata tags sent via Anthropic's `metadata.user_id` / OpenAI's `user` / Gemini's `metadata` fields.

**Interaction:** Hover shows tooltip with project cost + dominant model; click drills into a filtered view (breadcrumb updates).

### 2.6 Batch vs realtime split

A compact 2-bar chart (shadcn `<Card>` width = 1 col at `lg`):

```
Batch     ██████ $240   ← 50% discount tier
Realtime  ████████████████ $1,860
                  Realtime is 88% of spend.
                  Moving 20% of realtime to batch → save $372/mo.
```

Two horizontal bars, percentage labels, and an auto-generated optimization hint using the Anthropic Batch API and OpenAI Batch API pricing (already modeled in `anthropic_connector.py` / `openai_connector.py`).

### 2.7 Tool-use cost — grouped bar (not treemap, not donut)

Tool calls from Claude Code (Bash, Edit, Read, WebFetch, MCP, Task) and from OpenAI's function-calling surface separately:

```
┌──────────────────────────────────────────────────────────────────┐
│ Tool-use cost — 30 days                                          │
│                                                                  │
│ Read      ████████████████████  $180  42K calls  $0.0043/call  │
│ Edit      ██████████████        $130  8K calls   $0.0163/call  │
│ Bash      ██████████            $95   3K calls   $0.0317/call  │
│ WebFetch  █████████             $88   1.2K calls $0.0733/call  │
│ Task      ███████               $70   400 calls  $0.175/call   │
│ Grep      ████                  $40   12K calls  $0.0033/call  │
│ MCP       ██                    $22   800 calls  $0.0275/call  │
└──────────────────────────────────────────────────────────────────┘
```

**Choice: horizontal bars with inline per-call metrics.**

Why not treemap? Only ~7 tools — treemap over-engineers. Why not pie? Need the $/call metric inline; pies don't support that.

This is the most actionable AI-spend visualization for Claude Code users specifically — it answers "which tools are eating my budget per call?" A high $/call number on `Task` (sub-agents) signals the user should scope-down delegations.

**Data source.** Needs a new backend field on `claude_code_connector.py` (already scaffolded at `backend/app/services/connectors/claude_code_connector.py`). Tool usage is available from the Claude Code transcript JSONL files — parse and aggregate per-tool.

### 2.8 Session drill-down (project → conversation → turns)

```
Click a project tile in §2.5 ──→  opens right-side Drawer:

┌────────────────────────────── Drawer ──────────────────────────┐
│ costly-oss                                                  [×]│
│ 30-day spend: $890 · 214 conversations · 3,920 turns          │
│ ┌────────────────────────────────────────────────────────────┐│
│ │ Conversations (paginated, 50/page)                         ││
│ │ ────────────────────────────────────────────────────────── ││
│ │ Mar 18 · "debug the aws connector"     23 turns  $12.40  › ││
│ │ Mar 18 · "write dashboard spec"         8 turns  $6.80  › ││
│ │ Mar 17 · "refactor use-api hook"        4 turns  $1.20  › ││
│ │ ...                                                        ││
│ └────────────────────────────────────────────────────────────┘│
│                                                               │
│ Click a conversation → Turns table:                          │
│ ┌────────────────────────────────────────────────────────────┐│
│ │ # │ Model      │ In    │ Out   │ Cache │ Tools  │ $      ││
│ │ 1 │ sonnet-4   │ 1,200 │ 400   │ 0     │ Read×2 │ $0.04  ││
│ │ 2 │ sonnet-4   │ 8,400 │ 1,200 │ 7,200 │ —      │ $0.08  ││
│ │ 3 │ sonnet-4   │ 12K   │ 2,400 │ 11K   │ Edit×1 │ $0.14  ││
│ └────────────────────────────────────────────────────────────┘│
│ [Download transcript] [Ask agent about this session]         │
└────────────────────────────────────────────────────────────────┘
```

Three-level drill: project (treemap tile) → conversation (drawer list) → turn (drawer table).

**Components:** shadcn `<Sheet>` (already installed) for the drawer; shadcn `<Table>` for turns list; React state managed via URL search params (`?project=costly-oss&conv=abc123`) so drill-downs are deep-linkable.

**"Ask agent about this session"** CTA opens `/chat?q=analyze%20conversation%20abc123` with the conversation ID as context — the agent loads that transcript and reasons about it.

### 2.9 "Why did my spend spike?" timeline

A dedicated section below the main charts:

```
┌──────────────────────────────────────────────────────────────────┐
│ What happened this month                           [Collapse ⌃] │
├──────────────────────────────────────────────────────────────────┤
│ Mar 12 · 11:42 AM  ▲ +$240 spike                                │
│   ▸ Claude sonnet-4 tokens jumped from 2M/hr baseline to 18M   │
│   ▸ 94% from project: costly-oss                                │
│   ▸ Agent sub-task fan-out pattern — see conversation abc123    │
│   [View conversation] [Set alert for this pattern]              │
│                                                                  │
│ Mar 10 · 02:15 AM  ● Expected uptick                            │
│   ▸ Scheduled dbt job triggered — within 1σ of baseline        │
│                                                                  │
│ Mar 08 · 09:30 AM  ▼ −$180 drop                                 │
│   ▸ Cache hit rate jumped from 30% → 68%                        │
│   ▸ Caused by prompt caching enabled on gpt-4o-mini              │
└──────────────────────────────────────────────────────────────────┘
```

Vertical timeline, reverse-chronological. Each event has severity glyph (▲/▼/●), a headline, 1–3 sub-bullet explanations (produced by the anomaly agent — calls the Claude API with transcript summaries), and action buttons.

**Data source.** `/api/anomalies?page=ai&days=30`. The backend needs to store anomaly records with `root_cause` (free-text) and `related_entities` (project id, conversation id).

### 2.10 Filters & responsiveness

**Persistent filter bar** at top: date range, provider multi-select, model multi-select, project multi-select. All filters sync to URL. "Reset filters" button appears when any is active.

**Mobile (<768px):** Token-tier stacked area collapses to vertical stacked-bar (5 days shown, horizontal scroll). Horizontal bars (model, tool, batch) remain. Treemap replaced by ranked horizontal bar. Dial shrinks to 48×48 above trend line (stacked, not side-by-side).

**Dark mode:** All charts respect `prefers-color-scheme`. Grid stroke changes to `#1e293b`; axis tick color `slate-400`; bar fills unchanged (they're designed for both modes). Dial inner text becomes `slate-100`.

**A11y:** Each chart has a hidden `<table>` with the raw data for screen readers (Recharts doesn't do this by default; wrap in an `<a11y-chart-wrapper>` component that renders a `<table className="sr-only">`). Legend entries focusable with `tabindex=0`; space/enter toggles series.

---

## 3. Platforms page (`/platforms`)

### 3.1 Purpose

List of connected platforms. Lets the user see health at a glance, click into a per-platform deep dive, and add new connectors.

The page already exists at `frontend-next/src/app/(dashboard)/platforms/page.tsx` with a connector catalog and a list of connected platforms. This spec refines the layout.

### 3.2 Card grid vs table — **card grid wins, table as toggle**

```
┌──────────────────────────────────────────────────────────────────┐
│ Platforms                    [+ Add platform]  [Grid] [Table]   │
├──────────────────────────────────────────────────────────────────┤
│ ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│ │ ❄️ Snowflake    │  │ ☁️ AWS          │  │ 🤖 Anthropic    │  │
│ │ Connected  ●    │  │ Connected  ●    │  │ Connected  ●    │  │
│ │ $3,100 / 30d    │  │ $4,200 / 30d    │  │ $1,240 / 30d    │  │
│ │ ▁▂▃▅▇▆▅▇▇       │  │ ▃▅▂▃▅▆▇▇▇       │  │ ▁▁▂▃▅▆▇▇▇      │  │
│ │ Last synced 4m  │  │ Last synced 12m │  │ Last synced 3m  │  │
│ │ [Open →]        │  │ [Open →]        │  │ [Open →]        │  │
│ └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│                                                                  │
│ ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│ │ 🟠 dbt Cloud    │  │ 🔷 BigQuery     │  │ ➕ Add another  │  │
│ │ ⚠️ Sync failed  │  │ ● Syncing…      │  │                 │  │
│ │ $1,800 / 30d    │  │ …               │  │  dashed border  │  │
│ │ Retry now       │  │ spinner         │  │                 │  │
│ └─────────────────┘  └─────────────────┘  └─────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

**Rationale:**
- **Card grid** is the right default because each platform has multi-dimensional status (connected?, last synced, MTD cost, sparkline, health). Tables compress too aggressively.
- **Table toggle** is for power users managing 15+ connectors who want density. Columns: Platform, Status, Last synced, MTD cost, 7d Δ, Actions.
- **Disconnected** platforms show as opaque cards at the bottom with "Connect" CTA — so the full catalog is always one click away.

### 3.3 Card anatomy

Each card is a shadcn `<Card>` with:
- **Header:** emoji/logo + platform name + status dot (green=connected, amber=syncing, red=failed, grey=disconnected).
- **Body:**
  - MTD cost in large text
  - 30-day sparkline (Recharts `<LineChart>` 180×40, no axes, stroke `COLORS.primary`)
  - Last synced relative time + data freshness badge (from existing `DataFreshness` component at `components/data-freshness.tsx`)
- **Footer:** primary action `[Open →]` (routes to `/platforms/[platform]`), secondary overflow `[...]` menu (Edit credentials, Pause sync, Disconnect).

**Health signals.** A small colored bar at the top of the card encodes sync-health:
- Green (`#059669`): last synced <10min, sync success rate 100%
- Amber (`#D97706`): last synced <1hr OR sync success rate 80–99%
- Red (`#DC2626`): last synced >6hr OR sync success rate <80%
- Grey (`#94A3B8`): disconnected

### 3.4 Per-platform deep dive (`/platforms/[platform]`)

Already scaffolded at `frontend-next/src/app/(dashboard)/platforms/[platform]/`. Spec:

- Reuses AI-Spend page structure for AI platforms (Claude/OpenAI/Gemini) — they inherit the cache/token/model/tool panels from §2.
- For warehouse platforms (Snowflake/BigQuery/Databricks): warehouses/users/queries/storage tabs — existing pattern from `warehouses/page.tsx`, `queries/page.tsx`, etc.
- For pipeline platforms (dbt/Fivetran/Airbyte): jobs/connectors/freshness tabs.
- For CI platforms (GitHub Actions/GitLab CI): workflows/runners/minutes-by-repo tabs.

Each deep dive includes a "Platform score" card (custom SVG gauge 0–100) summarizing utilization + cost efficiency, and a "What the agent thinks" card with 2–3 agent-generated observations.

### 3.5 Mobile / dark mode / a11y

- Grid collapses to 1 column <640px, 2 columns <1024px, 3 columns ≥1024px.
- Dark mode: card background `slate-900`, border `slate-800`, text `slate-100`.
- Status dots have `aria-label="Connected"` / `"Sync failed 2h ago"` etc.
- Keyboard: Tab through cards; Enter opens deep dive; `Ctrl+,` opens edit credentials.

---

## 4. Anomalies page (`/anomalies`)

### 4.1 List vs kanban vs timeline — **hybrid list+timeline**

```
┌──────────────────────────────────────────────────────────────────┐
│ Anomalies                                                        │
│ [All] [Open] [Muted] [Resolved]   Platform: [All ⌄]  [30D ⌄]    │
├──────────────────────────────────────────────────────────────────┤
│ ● NEW · Today 09:42                               +$240 (+142%) │
│   Snowflake · ANALYTICS_WH · spike vs baseline                  │
│   Likely cause: new dbt job `fct_orders_v2` deployed 08:15      │
│   [Mute 7d] [Acknowledge] [Mark expected] [Investigate →]       │
│                                                                  │
│ ● NEW · Today 02:18                                +$62 (+88%)  │
│   OpenAI · gpt-4o-mini · token volume spike                     │
│   Likely cause: runaway loop in chat/page.tsx?                  │
│   [Mute 7d] [Acknowledge] [Mark expected] [Investigate →]       │
│                                                                  │
│ ○ Yesterday 14:30                                 +$18 (+22%)   │
│   AWS · us-east-1 · S3 egress above weekly average              │
│   Acknowledged by nitin@cdatainsights.com · noted               │
│                                                                  │
│ ◐ Yesterday 04:00                                 −$45 (−90%)   │
│   dbt Cloud · job_id=47 · drop in compute                       │
│   Muted 7d · auto-unmute Mar 25                                 │
└──────────────────────────────────────────────────────────────────┘
```

**Choice: vertical list with timeline glyphs.** Rejected kanban (Linear tried this for issues and it works for short lifecycles; cost anomalies have 4 states not 4 columns, so the kanban overhead doesn't pay). Rejected pure timeline (hides actionable detail).

**Each anomaly row** shows:
- Status glyph: `●` new / `○` acknowledged / `◐` muted / `✓` resolved
- Relative timestamp
- **Magnitude** in `$` and `%` — both matter, a 300% increase on a $5 baseline is noise, a 20% increase on $10K is action.
- **Platform + resource**
- **Probable cause** — auto-generated by a lightweight classifier (correlate with recent deploys, config changes, or other anomalies). Falls back to "Unknown cause" if confidence <50%.
- **Quick actions** row: Mute (7d/30d/permanent), Acknowledge (marks seen but open), Mark expected (tells the detector "this is normal for us"), Investigate → (opens full drawer + agent context).

### 4.2 Anomaly detail drawer

```
Opens on "Investigate →":

┌──────────────── Drawer (right, 600px) ──────────────────┐
│ Snowflake ANALYTICS_WH spike   Today 09:42        [×]  │
│                                                         │
│ Spend   $240 today   Baseline 7d avg $100   Δ +140%    │
│                                                         │
│ ┌────────────────────────────────────────────────────┐ │
│ │ Hourly spend — last 7 days                         │ │
│ │ (bar chart, today in red, prior 6 days in grey)    │ │
│ └────────────────────────────────────────────────────┘ │
│                                                         │
│ What we think happened                                 │
│ ▸ dbt job fct_orders_v2 deployed 08:15 matches ramp   │
│ ▸ Query QRY_abc123 ran 47× (1× typical)                │
│ ▸ ANALYTICS_WH auto-suspend = 600s (high)              │
│                                                         │
│ Related                                                │
│ · Conversation with agent about fct_orders  [Open]     │
│ · Query QRY_abc123 · $140 / 47 runs  [Open]           │
│                                                         │
│ Actions                                                │
│ [Mute] [Acknowledge] [Mark expected]                   │
│ [Ask agent to fix] [Create budget alert]               │
└─────────────────────────────────────────────────────────┘
```

**Key:** every anomaly can be sent to the agent for investigation (`[Ask agent to fix]` → `/chat?q=why+did+X+spike&context=anomaly:abc123`).

### 4.3 False-positive controls

- **Mute 7d / 30d / forever** — suppresses future anomalies with same signature (platform + resource + type).
- **Mark expected** — adds to a user allow-list; detector learns the baseline includes this pattern.
- **Acknowledge** — keeps the anomaly but hides from default view.
- **Feedback:** each anomaly row has a discrete thumbs-up/down; feeds back into anomaly scoring weights.

Muted/expected lists are editable from `Settings → Anomaly rules`.

### 4.4 Components / responsiveness

- shadcn `<Card>` per row in list view; `<Sheet>` for detail drawer.
- Filters: shadcn `<Select>` + `<Tabs>` for status pills.
- Mobile: actions collapse into an overflow `<DropdownMenu>`; magnitude moves below headline.
- Dark mode: red shifts to `red-400` (accessibility against dark background); green `emerald-400`.

---

## 5. Recommendations page (`/recommendations`)

### 5.1 Layout — stack-ranked list by projected savings

```
┌──────────────────────────────────────────────────────────────────┐
│ Recommendations                         Sort: [Savings ⌄] [Risk]│
│ Total projected savings: $2,140 / mo · 12 recs                  │
├──────────────────────────────────────────────────────────────────┤
│ [History]  [Open]  [Applied]  [Dismissed]                       │
│                                                                  │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ 1. Resize ANALYTICS_WH from X-Large to Large                ││
│ │    SAVING $340/mo · EFFORT low · RISK low · CONFIDENCE 92%   ││
│ │    Snowflake · ANALYTICS_WH · 4 days of evidence             ││
│ │                                                              ││
│ │    ```sql                                                    ││
│ │    ALTER WAREHOUSE ANALYTICS_WH SET WAREHOUSE_SIZE = 'LARGE'││
│ │    ```                                                       ││
│ │                                                              ││
│ │    [Apply via GitHub PR] [Copy SQL] [Dismiss] [Snooze 30d]  ││
│ │    ▸ Show evidence (utilization <40% for last 14d, etc.)     ││
│ └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ 2. Enable prompt caching for gpt-4o-mini                     ││
│ │    SAVING $230/mo · EFFORT med · RISK low · CONFIDENCE 85%   ││
│ │    OpenAI · chat/page.tsx lines 52-78                        ││
│ │                                                              ││
│ │    ```typescript                                             ││
│ │    // diff preview — 3 lines added                           ││
│ │    + cache: { enabled: true, ttl: 3600 },                    ││
│ │    ```                                                       ││
│ │                                                              ││
│ │    [Apply via GitHub PR] [Copy diff] [Dismiss]              ││
│ └──────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────┘
```

### 5.2 Per-recommendation shape

- **Rank number** (1, 2, …) — makes the stack-ordering instantly clear.
- **Title** — one line, verb-first ("Resize", "Enable", "Drop", "Migrate").
- **Metrics row:** savings ($/mo), effort (low/med/high badge), risk (low/med/high badge), confidence (%).
- **Scope:** platform + resource path.
- **Actionable artifact:** SQL snippet / config diff / code snippet with syntax highlighting (use shiki or `react-syntax-highlighter`; keep it minimal — lazy-load).
- **Actions:**
  - `[Apply via GitHub PR]` — opens a dialog that lets the user pick a repo + branch, then uses the GitHub API to open a PR with the diff. Requires GitHub App install (new connector).
  - `[Copy SQL/diff]` — clipboard copy.
  - `[Dismiss]` — removes from active list, logged to History.
  - `[Snooze 30d]` — hides for a month.
- **Expandable evidence:** click "Show evidence" to reveal the data that drove the recommendation (utilization charts, query patterns, etc.).

### 5.3 History view

Separate tab showing recs that have been applied or dismissed:

```
┌──────────────────────────────────────────────────────────────────┐
│ Applied (8)                                                      │
├──────────────────────────────────────────────────────────────────┤
│ Mar 14 · Resize COMPUTE_WH → Medium                             │
│   Projected $180/mo · Actual $195/mo (+8%) over 14d  ✓ Kept    │
│                                                                  │
│ Mar 10 · Enable Anthropic prompt caching                        │
│   Projected $120/mo · Actual $144/mo (+20%) over 21d  ✓ Kept   │
│                                                                  │
│ Mar 02 · Drop stale table RAW.OLD_EVENTS                        │
│   Projected $60/mo · Actual $58/mo (−3%) over 49d  ✓ Kept      │
└──────────────────────────────────────────────────────────────────┘
```

Shows projected vs actual savings to build trust. "Realized savings to date: $X,XXX" header aggregates across all applied recs.

### 5.4 Components / responsiveness

- shadcn `<Card>` per rec; shadcn `<Dialog>` for GitHub PR picker; shadcn `<Tabs>` for Open/Applied/Dismissed.
- Syntax-highlighted code via `react-syntax-highlighter` (~30KB gzipped, acceptable).
- Mobile: action row wraps; syntax block becomes horizontally scrollable.
- Dark mode: code block uses `vscode-dark-plus`; metric badges keep their color but with dark-tuned backgrounds.
- a11y: recommendation cards are `<article>` with `aria-labelledby` pointing to the title; action buttons have clear labels.

---

## 6. Budgets page (`/budgets`)

### 6.1 Purpose

Per-platform or per-team budgets with burn-rate projection and alerts.

### 6.2 Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ Budgets                                     [+ New budget]      │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ AI spend — March 2026       $2,240 of $3,000 used (75%)      ││
│ │ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 75%        ││
│ │ ⚠ 12 days until exhaust at current burn rate                 ││
│ │                                                              ││
│ │ Burn chart ─ projection vs actual                            ││
│ │ $3,000┤ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ budget line        ││
│ │ $2,500┤                          ╱── forecast ───┐          ││
│ │       │                      ╱╱╱                 │          ││
│ │ $2,000┤                ╱╱╱          exhaust Mar 23          ││
│ │       │          ╱╱╱                                        ││
│ │ $1,000┤    ╱╱╱                                              ││
│ │       │╱╱╱                                                  ││
│ │     0 └─────────────────────────────────────────            ││
│ │        Mar 01       Mar 15       Mar 31       Apr 10       ││
│ │                                                              ││
│ │ Alerts: 50% ✓ sent · 75% ✓ sent · 90% pending · 100%        ││
│ │ [Edit budget] [View recommendations]                         ││
│ └──────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────┘
```

Each budget is a shadcn `<Card>` with:
- **Progress bar** (slim, 4px, `bg-sky-500` up to 75%, `amber-500` at 75–90%, `red-500` 90%+).
- **"Days of runway" callout** — the single most useful metric. Linear extrapolation from last 7 days.
- **Burn chart** — Recharts `<AreaChart>` with two series: actual spend (solid area) and forecast (dashed line extending past today). Budget line rendered as `<ReferenceLine y={budget_amount}>`. Exhaust point marked with `<ReferenceDot>`.
- **Alert rules** summary: thresholds (50/75/90/100%) with send-status per.

### 6.3 New budget form

Full-page form or modal dialog:

- **Name**
- **Scope:** platform multi-select | team | tag (metadata-based) | "all spend"
- **Period:** monthly (default) | weekly | quarterly | custom
- **Amount:** $ input
- **Alert thresholds:** default 50/75/90/100%, editable; per-threshold channels (email, Slack, webhook)
- **Actions on 100%:** none (alert only) | pause non-critical connectors (advanced, future)

### 6.4 Alert rules UI

Each threshold row:
```
[50%]  ✓ Email   ☑ Slack #finops    ☐ Webhook   [Edit]
[75%]  ✓ Email   ☑ Slack #finops    ☐ Webhook   [Edit]
[90%]  ✓ Email   ☑ Slack #finops    ☑ Webhook   [Edit]
[100%] ✓ Email   ☑ Slack #finops    ☑ Webhook   [Edit]
```

Shadcn `<Checkbox>` grid. Each channel pulls config from Settings → Integrations.

### 6.5 Components / mobile / a11y

- shadcn `<Card>`, `<Progress>` (add via `npx shadcn@latest add progress`), `<Dialog>`, `<Select>`, `<Input>`.
- Recharts `<AreaChart>` with dashed `<Line>` for forecast + `<ReferenceLine>` + `<ReferenceDot>`.
- Mobile: burn chart collapses to a simpler progress ring + "12 days of runway" callout; full chart hidden behind "View chart".
- a11y: progress bar has `role="progressbar"`, `aria-valuenow`, `aria-valuemin`, `aria-valuemax`. Percentage also rendered as visible text for redundancy.

---

## 7. Conversational agent page (`/chat`)

Existing page at `frontend-next/src/app/(dashboard)/chat/page.tsx`. This spec extends it with transparency, tool-call visibility, inline charts, saved queries, and cost disclosure — patterns stolen from Claude's own UI and from Langfuse's observability view.

### 7.1 Full layout

```
┌──────────────────────────────────────────────────────────────────┐
│ Costly AI                                 [Saved] [History] [⚙] │
│ Ask anything about your data platform spend                     │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│ 👤 You                                                           │
│    Why did OpenAI spend double this week?                       │
│                                                                  │
│ ✨ Costly · Snowflake Expert  (cost $0.04)                       │
│    ┌────────────────────────────────────────────────────────┐   │
│    │ ▸ tool:get_daily_cost(platform=openai, days=14)  ✓    │   │
│    │ ▸ tool:get_top_models(platform=openai, days=7)   ✓    │   │
│    │ ▸ tool:compare_periods(this_week vs last_week)   ✓    │   │
│    └────────────────────────────────────────────────────────┘   │
│                                                                  │
│    OpenAI spend doubled from $230 → $465 this week, driven by   │
│    a 4× jump in **gpt-4o** tokens (vs gpt-4o-mini baseline).    │
│                                                                  │
│    ┌──────── Inline chart (rendered by agent) ────────────┐    │
│    │ Daily OpenAI spend — last 14 days                    │    │
│    │ (stacked bar: gpt-4o-mini vs gpt-4o, 14 days)        │    │
│    └──────────────────────────────────────────────────────┘    │
│                                                                  │
│    Most likely cause: project `pangea-mvp` shipped a feature   │
│    on Mar 14 that routes to gpt-4o instead of gpt-4o-mini.     │
│                                                                  │
│    Sources · [costs.daily_spend] · [models.breakdown]           │
│                                                                  │
│    Follow-up: "Downgrade pangea-mvp back to gpt-4o-mini?"       │
│                                                                  │
│    [💾 Save query] [🔁 Re-run] [📋 Copy]                        │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│ [textarea input]                                        [Send]  │
└──────────────────────────────────────────────────────────────────┘
```

### 7.2 Message anatomy

**User message.** Avatar (initials), right-aligned bubble, `slate-100` bg. Markdown-rendered.

**Agent message.** Avatar (sparkles icon + `bg-gradient-to-br from-sky-500 to-blue-600` matches existing page). Left-aligned, `white` bg, border `slate-200`.

**Expert badge.** Next to "Costly": if the agent delegated to a platform expert (Snowflake Expert, AWS Expert, etc. per `costly-expert-agents.md` in memory), show the expert name as a colored badge. This is already partially implemented via `EXPERT_COLORS` in the existing chat page.

**Cost disclosure.** Next to each agent message: `(cost $0.04)`. Sum of all model calls + tool calls for that turn. Click opens a mini-breakdown showing input tokens, output tokens, cache-read tokens, model used, cost per 1K. Matches Stripe's "nothing hidden" philosophy. See [stripe.com](https://stripe.com/) pricing transparency.

### 7.3 Tool-call transparency

Inline collapsed-by-default block showing each tool the agent called in order:

```
▸ tool:get_daily_cost(platform=openai, days=14)  ✓ (142ms)
▸ tool:get_top_models(platform=openai, days=7)   ✓ (89ms)
▸ tool:compare_periods(this_week vs last_week)   ✓ (61ms)
```

Expandable to show raw JSON input + result. Inspired by Langfuse's trace-view UI.

Uses shadcn `<Collapsible>` (add if not installed).

### 7.4 Inline charts rendered by the agent

The agent can emit a special markdown code-fence:

````
```costly-chart
{
  "type": "stacked_bar",
  "title": "Daily OpenAI spend — last 14 days",
  "data": [...],
  "stack_keys": ["gpt-4o-mini", "gpt-4o"]
}
```
````

A custom `react-markdown` component parser (`components.code`) detects `language-costly-chart`, JSON-parses the fenced content, and renders a Recharts chart matching the spec. Supported types: `line`, `bar`, `stacked_bar`, `area`, `stacked_area`, `pie`, `kpi`, `table`.

This is the big UX win vs plain-text chat: the agent *shows* answers, doesn't just type them. Helicone and Langfuse don't do this; it's a genuine differentiator.

### 7.5 Citations / sources

Every assistant turn ends with a `Sources:` line listing which internal APIs or views were queried. Each source is clickable — opens the underlying dashboard page with the same filter applied. E.g. `[costs.daily_spend]` → `/costs?platform=openai&days=14`.

### 7.6 Follow-ups

Agent appends up to 3 one-line follow-up suggestions. Each is a chip; click = auto-send. Reduces blank-input friction.

### 7.7 Saved queries

Users can star any turn (💾 Save query). Saved queries appear in a left-side panel (collapsible) or in the `[Saved]` tab in the header. Each saved query shows:
- The original question
- Last-run timestamp + cost
- "Re-run" button — auto-sends, opens fresh turn.

Model: `saved_queries` collection in MongoDB. Fields: `user_id`, `question`, `answer_snapshot`, `cost`, `created_at`, `pinned`.

### 7.8 History

Left sidebar lists conversations, grouped by date (Today / Yesterday / Last 7 days / Older), each with the first user message as the title. Click to reload. New conversation button at top. Pattern borrowed from claude.ai and chat.openai.com.

On mobile: history slides out from left via shadcn `<Sheet>`.

### 7.9 Cost disclosure details

"This cost $0.03 to answer" appears inline with every agent turn. Clicking expands:

```
$0.032 breakdown
├─ Model: claude-sonnet-4  · 3,200 in · 640 out · 2,100 cached · $0.024
├─ Tool: get_daily_cost     · 2 calls                        · $0.001
├─ Tool: get_top_models     · 1 call                         · $0.002
└─ Tool: compare_periods    · 1 call                         · $0.005
```

This is genuinely novel for a cost-intelligence product — the agent that tells you about costs is transparent about its own cost. Builds trust, and lets users configure a per-query budget cap.

### 7.10 Components / mobile / dark mode / a11y

- shadcn: `<Card>`, `<Avatar>`, `<Textarea>`, `<Button>`, `<Sheet>` (history on mobile), `<Collapsible>` (tool calls), `<Badge>` (expert), `<Dialog>` (cost breakdown).
- Recharts for inline `costly-chart` blocks.
- Mobile: history sidebar hidden by default, opens via a hamburger. Input sticks to bottom, safe-area padding respected.
- Dark mode: already spec'd in the existing sidebar; agent bubble switches to `slate-800` bg, border `slate-700`. Tool-call lines use `slate-400` text.
- a11y: Input has `aria-label="Ask Costly"`. New message streaming region is `aria-live="polite"`. Cost disclosure has `role="button"` and `aria-expanded` for the breakdown.

---

## 8. Settings / Connections

### 8.1 Top-level settings nav

Tabs: `Profile` / `Connections` / `Budgets` (links to §6) / `Alerts` / `Team` / `Integrations` (Slack, email, webhooks) / `API` / `Pricing overrides` / `Danger`.

### 8.2 Per-connector setup flow

The existing page at `/platforms` (`page.tsx`) uses a modal dialog keyed by connector. Spec refinements:

**Unified shape** for every connector:

1. **Step 1 — Pick connector.** Catalog grid (already there).
2. **Step 2 — Auth.** Form per connector's `fields` (already modeled in `CONNECTORS` constant). Each field has a per-connector help link (docs tooltip) and an inline "test this field" (for multi-field creds like Snowflake key-pair).
3. **Step 3 — Scope.** Choose what to ingest (e.g. for AWS: which accounts; for Snowflake: which databases; for OpenAI: which projects). Default = "all".
4. **Step 4 — Test connection.** Live click-to-test. Shows success ✓ or specific error (not "failed", but "AWS Cost Explorer API not enabled — enable here").
5. **Step 5 — Activate & first sync.** Async; progress shown in a toast + in the connector card.

**Components:** shadcn `<Dialog>` (current), convert to a stepper using shadcn `<Tabs>` or a custom stepper component.

### 8.3 `pricing_overrides` input — form-field friendly

The raw data model is a per-SKU dict (e.g. `{"claude-sonnet-4": {"input": 0.003, "output": 0.015, "cache_read": 0.0003}}`). The UI:

```
┌──────────────────────────────────────────────────────────────────┐
│ Pricing overrides                              [+ Add override] │
│ Use these when your negotiated rate differs from list prices.   │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│ Anthropic                                                        │
│ ┌────────────────────────────────────────────────────────────┐  │
│ │ Model: claude-sonnet-4-20250514                            │  │
│ │ Input  $ 0.003  / 1K    (list: $0.003)   ✓ matches list    │  │
│ │ Output $ 0.012  / 1K    (list: $0.015)   ↓ 20% discount    │  │
│ │ Cache-read  $ 0.00024 / 1K (list: $0.0003) ↓ 20% discount  │  │
│ │ Cache-write-5m  $ 0.00375 / 1K (list: $0.00375) ✓           │  │
│ │ Cache-write-1h  $ 0.006 / 1K   (list: $0.006)   ✓           │  │
│ │ [Remove override]                                           │  │
│ └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│ Snowflake                                                        │
│ ┌────────────────────────────────────────────────────────────┐  │
│ │ Account: xy12345.us-east-1                                 │  │
│ │ Credit rate  $ 2.80 / credit  (Standard edition list $3)   │  │
│ │ Storage rate $ 23   / TB/mo   (list $40)  ↓ 43% discount   │  │
│ │ [Remove override]                                           │  │
│ └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

**UX details:**
- Each override is a self-contained card with labeled `$` input per SKU.
- Right-aligned "list price" reminder + delta badge shows the user whether they're actually saving.
- A "Bulk import from JSON" advanced option is tucked behind a link for users who have complex overrides.
- Values validated with Zod schema at submit; errors shown inline.
- Re-syncing: when overrides change, backend re-computes the last 90 days of cost on the fly (no re-pull from vendor APIs).

### 8.4 Components / mobile / dark mode / a11y

- shadcn `<Dialog>`, `<Form>` (add via shadcn — uses react-hook-form under the hood), `<Input>`, `<Select>`, `<Switch>`.
- Mobile: each connector override card is full-width; "list price" text wraps below input.
- a11y: `$` input has `inputMode="decimal"`, `aria-describedby` pointing to list-price text.

---

## 9. Cross-cutting concerns

### 9.1 Data model expectations

Each page assumes these API endpoints (some exist, some need to be added):

| Page | Endpoint | Status |
|------|----------|--------|
| Overview | `/api/dashboard?days=N` (exists), `/api/anomalies?days=N` (add), `/api/forecast?days=N` (add), `/api/cache-savings?days=N` (add) | Partial |
| AI Spend | `/api/ai-costs?days=N` (exists) — extend with `cache_read`, `cache_write_5m`, `cache_write_1h` tiers, tool-use breakdown, session hierarchy | Extend |
| Platforms | `/api/connections` (exists), `/api/connections/{id}/health` (add) | Partial |
| Anomalies | `/api/anomalies` (add full CRUD + mute/ack/expected endpoints) | Add |
| Recommendations | `/api/recommendations` (exists) — extend with `code_snippet`, `github_pr_url`, `applied_at`, `realized_savings` | Extend |
| Budgets | `/api/budgets` (add full CRUD, `/evaluate` endpoint) | Add |
| Chat | `/api/chat` (exists) — extend response with `tool_calls[]`, `cost`, `expert`, `sources[]`, `follow_ups[]`, `charts[]` | Extend |
| Settings | `/api/connections/*` (exists), `/api/pricing-overrides` (add) | Partial |

Response envelope follows the project convention (see `lib/api.ts` Axios instance): bare data on success, HTTP status + error body on failure. Consistent with `ApiResponse<T>` pattern in typescript/patterns.md.

### 9.2 State management

- Server data: `useApi<T>` hook (exists at `hooks/use-api.ts`). No need for SWR/TanStack Query.
- URL state: filters/date-range via search params. Enables deep-linkable drill-downs.
- Client UI state: React `useState` within page components. Avoid Redux/Zustand — the app is read-heavy and short-lived sessions.

### 9.3 Performance budgets

- TTFB: <300ms (cached), <1.5s (uncached). Redis cache with 60s TTL for dashboard endpoints (already implemented).
- First Contentful Paint: <1s on Overview.
- Largest Contentful Paint: <2.5s. Hero stacked-area chart is the LCP element.
- Lazy-load `d3-sankey`, `react-syntax-highlighter`, and chart-heavy drawers. Use `next/dynamic`.
- Don't render off-screen charts. Use `IntersectionObserver` via `react-intersection-observer` to defer rendering until scrolled near.

### 9.4 Accessibility checklist (WCAG 2.1 AA)

- All interactive elements have a visible focus ring (`focus-visible:ring-2 ring-sky-500 ring-offset-2`).
- Contrast ratio ≥4.5:1 for normal text, 3:1 for large text + UI elements. The existing palette satisfies this in light mode; dark mode uses `slate-100` foreground on `slate-900` bg (~15:1).
- Charts have `<title>` and `<desc>` SVG elements + a hidden screen-reader table with raw values.
- Keyboard navigation: every page accessible without a mouse; Tab order follows visual order; `⌘K` opens agent anywhere.
- `aria-live="polite"` for streaming agent responses and data-refresh toasts.
- Motion-reduced: respect `prefers-reduced-motion` — disable enter/exit animations on charts.

### 9.5 Dark mode details

Current app defaults to light on dashboard; marketing dark. To support a toggle:

- Add a `<ThemeProvider>` using the `next-themes` lib (drop-in for App Router).
- Extend `COLORS.chart` with dark-mode variants or confirm existing ramp passes contrast on both backgrounds (rough check: yes, the 8-color ramp works on both).
- Card `bg-white` → `bg-slate-900` in dark. Border `border-slate-200` → `border-slate-800`.
- Recharts grid `stroke="#f1f5f9"` → `#1e293b` in dark. Use a small `useTheme()` wrapper in each chart.
- Image/logo assets: SVGs use `currentColor` where possible; platform logos stay colored (they're brand).

### 9.6 Empty / error / loading states

**Every page needs all four states.**

- **Loading:** shadcn `<Skeleton>` blocks matching the final layout (already implemented on Overview).
- **Empty (no data yet):** illustrated card with CTA. Per-page illustrations are lucide icons at `h-12 w-12 text-slate-300`. Overview §1.6 is the reference.
- **Error (API failed):** inline `<Alert variant="destructive">` with the error message and a retry button. Never leave the user staring at a blank chart.
- **Partial (one connector failing):** banner at top of affected page: `⚠ dbt Cloud sync failed at 09:12 — data may be stale`. Link to `/platforms/dbt_cloud` for retry.

---

## 10. Implementation priority

Costly is building toward W26 YC (Sep 2026) with a goal of 10 paying users and $1-2K MRR (per `costly-ai-agent.md` memory). Every build decision should shorten time-to-first-"wow" for a new signup.

### 10.1 Ship order (recommended)

**Phase 1 — Minimum surprise (ships week 1):**

1. **Overview** (§1) — extend the existing `dashboard/page.tsx` with the 6-KPI layout, annotation layer on the hero chart, and agent prompt pill. This is where every user lands and makes a go/no-go judgment in 10 seconds. Pay special attention to cache-savings KPI (our wedge) and the empty state (§1.6).
2. **AI Spend** (§2) — the hero differentiator vs Vantage/CloudZero. Ship the cache-hit dial + trend, per-model horizontal bars, token-tier stacked area, and batch-vs-realtime split first. Defer the tool-use chart (§2.7), alluvial toggle (§2.3), and session drill-down (§2.8) to Phase 2.
3. **Platforms** (§3) — minor refinement of the existing page; add sparklines, status bar, and grid/table toggle. Low effort, high polish payoff.

**Phase 2 — Depth (ships weeks 2–4):**

4. **Conversational agent page** (§7) — extend existing `chat/page.tsx`: add tool-call transparency (§7.3), cost disclosure (§7.9), inline chart rendering (§7.4), saved queries (§7.7). Follow-ups and sources require minor backend work. This turns a toy chat into a differentiator.
5. **Recommendations** (§5) — ship the stack-ranked list + `[Copy SQL]` action first. `[Apply via GitHub PR]` deferred — requires GitHub App install.
6. **Anomalies** (§4) — ship list + detail drawer + mute/ack. Root-cause correlation can be simple (deploy-time matching) first, ML-driven later.

**Phase 3 — Moat (ships weeks 5–8):**

7. **Budgets** (§6) — full burn chart + alert rules + Slack/email delivery. Forecast accuracy improves with historical data, so this benefits from waiting a few weeks.
8. **Settings / Pricing overrides** (§8.3) — critical for enterprise users (who always negotiate custom rates) but not required for the initial 10 users, who will use list prices. Ship when the first "please let me override" ticket comes in.
9. **AI Spend advanced** — tool-use breakdown (§2.7), alluvial sankey (§2.3), session drill-down (§2.8), "why did my spend spike" timeline (§2.9).
10. **Recommendations — Apply via GitHub PR** (§5.2) — killer feature, but blocked on GitHub App setup; defer until #7 is validated.

### 10.2 Why this order

- **Overview + AI Spend first** because they're the demo. When a prospect loads costly.cdatainsights.com, the first 20 seconds decide everything. Our wedge is unified AI spend intelligence — that has to be visible on the landing dashboard.
- **Chat second** because it's a differentiator vs Vantage/CloudZero (neither has a good agent experience) and the existing page already works — it just needs transparency polish.
- **Recommendations over Anomalies** because recommendations have a clearer ROI narrative ("applying this saves $340/mo") whereas anomalies are table-stakes that every FinOps tool has.
- **Budgets and Settings last** because they require user-specific configuration — they're blockers for power users but don't help first impression.

### 10.3 Effort estimates (rough)

| Page | Frontend effort | Backend effort | Total |
|------|----------------|----------------|-------|
| Overview | 3–4 days | 2 days (anomaly + forecast endpoints) | ~1 week |
| AI Spend Phase 1 | 5–6 days | 3 days (token tier extension) | ~1.5 weeks |
| Platforms refinement | 1–2 days | 1 day (health endpoint) | ~3 days |
| Chat extensions | 4 days | 4 days (tool-call metadata, chart emission) | ~1.5 weeks |
| Recommendations | 3 days | 2 days | ~1 week |
| Anomalies | 3 days | 4 days (mute/ack + root cause) | ~1.5 weeks |
| Budgets | 4 days | 3 days | ~1.5 weeks |
| Settings / pricing overrides | 2 days | 2 days | ~1 week |

**Total:** ~9 weeks solo, ~5 weeks with a second eng. Matches the W26 apply timeline (Sep 2026).

---

## 11. References

- Vantage product page — [vantage.sh](https://vantage.sh/) — FinOps dashboard patterns.
- CloudZero product — [cloudzero.com](https://www.cloudzero.com/) — cost allocation, unit economics, anomaly detection UI.
- Finout product — [finout.io/product](https://www.finout.io/product) — FinOps, virtual tags, MegaBill.
- Select.dev — [select.dev](https://select.dev/) — Snowflake-specific cost observability patterns.
- Revefi — [revefi.com](https://www.revefi.com/) — automation-first recommendation UI.
- Helicone — [us.helicone.ai](https://us.helicone.ai/) — LLM observability (now part of Mintlify).
- Langfuse analytics — [langfuse.com](https://langfuse.com/) — trace/session dashboard patterns.
- Linear — [linear.app](https://linear.app/) — dashboard density reference.
- Vercel Analytics — [vercel.com/analytics](https://vercel.com/analytics) — KPI + sparkline + breakdown table patterns.
- Stripe Dashboard — [stripe.com](https://stripe.com/) — fee transparency and price-per-action disclosure.
- PostHog — [posthog.com](https://posthog.com/) — heatmap and retention chart inspiration.
- Observable Plot — [observablehq.com/plot](https://observablehq.com/plot/) — chart mark vocabulary.
- Apache ECharts — [echarts.apache.org](https://echarts.apache.org/) — chart gallery for token-tier / alluvial inspiration.
- Existing codebase:
  - `CLAUDE.md`
  - `frontend-next/src/app/(dashboard)/dashboard/page.tsx`
  - `frontend-next/src/app/(dashboard)/ai-costs/page.tsx`
  - `frontend-next/src/app/(dashboard)/overview/page.tsx`
  - `frontend-next/src/app/(dashboard)/chat/page.tsx`
  - `frontend-next/src/app/(dashboard)/platforms/page.tsx`
  - `frontend-next/src/lib/constants.ts`
  - `backend/app/services/connectors/` (16 connectors)

---

## Change log

### 2026-04-24 — Anomalies page shipped (lane/ui)

Shipped §4 end-to-end:

- New route `/anomalies` with the hybrid list-plus-timeline layout described in §4.1.
- Row-level actions: `Acknowledge` (calls `POST /api/anomalies/:id/acknowledge`), `Mute 7d / 30d / forever`, `Mark expected`, `Investigate`. Mute/expected are currently local-only (localStorage) until a backend endpoint is added — see `frontend-next/src/lib/anomalies.ts`.
- Detail drawer (§4.2) via shadcn `<Sheet>` — 14-day hourly-ish Recharts bar (anomaly day in red), probable cause, "Ask agent" shortcut that pre-seeds `/chat?q=...`.
- KPI strip: open / impact-today / acknowledged / muted counts (§1.2 style).
- Platform and status filters synced to local state (URL persistence deferred to a follow-up).
- Empty, loading, error states; muted / expected signatures list with "Clear" action.
- Dark-mode compatible (uses design tokens); ARIA labels on status badges, keyboard-navigable actions.
- Fallback path: when the backend returns zero anomalies, the page derives spikes from `/api/platforms/costs` `daily_trend` using a z-score rule (threshold 2σ) so a new install still sees something actionable.
- Pure-function tests in `frontend-next/src/lib/anomalies.test.ts` — covers signature stability, normalization, mute window expiry, z-score derivation, and storage round-trip.
- Sidebar: new "Anomalies" link between Recommendations and Alerts.

Files touched (frontend-next only):
- `src/app/(dashboard)/anomalies/page.tsx` (new)
- `src/components/anomalies/anomaly-row.tsx` (new)
- `src/components/anomalies/anomaly-detail-sheet.tsx` (new)
- `src/lib/anomalies.ts` (new, pure logic)
- `src/lib/anomalies.test.ts` (new, pure tests)
- `src/components/sidebar.tsx` (nav entry)
- `docs/dashboard-visualization-spec.md` (this change log)
- `docs/lanes/ui.md` (new — persistent lane notes)

Backend contract: the page reads `GET /api/anomalies?days=N` and `POST /api/anomalies/:id/acknowledge`. `POST /api/anomalies/detect` is called by the Re-scan button. Mute/mark-expected endpoints are **not** yet wired — they are the obvious next backend task. The page degrades gracefully when the backend is offline or returns an empty list.

---

_End of spec. Feedback welcome via GitHub Issues on [njain006/costly-oss](https://github.com/njain006/costly-oss)._
