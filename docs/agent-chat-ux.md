# Costly Agent Chat — UX Specification

**Status:** Draft v1
**Owner:** Nitin Jain
**Target surface:** `/chat` on costly.cdatainsights.com
**Last updated:** 2026-04-23

---

## 0. Purpose and success criteria

Costly's conversational agent is a single text box that spans 15+ connectors (Anthropic, OpenAI, Gemini, Claude Code, Cursor, Snowflake, BigQuery, Databricks, dbt Cloud, Fivetran, Hightouch, Airflow, AWS, GCP, Azure, and a handful of BI tools). Today the `/chat` route is a plain message-list + bubble UI. This spec brings it up to the quality bar users already expect from Cursor ([cursor.com](https://cursor.com)), Linear ([linear.app](https://linear.app)), Arc ([arc.net](https://arc.net)), Vercel v0 ([v0.dev](https://v0.dev)), Perplexity ([perplexity.ai](https://perplexity.ai)), and Claude.ai ([claude.ai](https://claude.ai)).

Success criteria:
- A new user can open `/chat`, ask "what did we spend on Claude last week and where is it growing?" and in <8 seconds see a grounded, cited, chart-bearing answer with clear follow-ups.
- A returning user can recall any past conversation within 2 clicks and re-run it with a different time range.
- An exec can take any answer and ship it as a scheduled Slack digest in under 30 seconds.
- Every dollar figure in the UI is traceable to a source row, a tool call, and a freshness timestamp — no "trust me" numbers.

Inspirations that this spec references throughout:
- Cursor chat pane and "new chat" affordances — [cursor.com/docs](https://cursor.com/docs)
- Linear's agent chat-style updates and triage UX — [linear.app/changelog](https://linear.app/changelog)
- Arc browser's Ask-on-page and Browse for Me — [arc.net/max](https://arc.net/max)
- v0 generative UI blocks — [v0.dev](https://v0.dev)
- Perplexity citations and follow-up chips — [perplexity.ai](https://perplexity.ai)
- Claude.ai composer, artifacts, Projects — [claude.ai](https://claude.ai)
- Stripe Sigma assistant (natural-language SQL over Stripe data) — [stripe.com/sigma](https://stripe.com/sigma)
- Supabase SQL assistant — [supabase.com/blog/sql-editor-ai-assistant](https://supabase.com/blog/sql-editor-ai-assistant-v2)
- LangSmith trace + tool-call transparency — [smith.langchain.com](https://smith.langchain.com)
- PostHog LLM observability — [posthog.com/docs/llm-analytics](https://posthog.com/docs/llm-analytics)
- Langfuse trace viewer — [langfuse.com/docs/tracing](https://langfuse.com/docs/tracing)
- Helicone session view — [helicone.ai/sessions](https://helicone.ai)
- Arize Phoenix trace UI — [phoenix.arize.com](https://phoenix.arize.com)

---

## 1. Layout and information architecture

The page is a three-column shell, collapsible to two or one. Breakpoints follow Tailwind's defaults: `lg` (1024px) = three columns, `md` (768px) = two, below = single with swipe.

### 1.1 Desktop wireframe (lg, three columns)

```
+------------------------------------------------------------------------------+
| Costly   [New chat +]   [Share]   [Mar 1 - Mar 31 ▼]   [Claude 4.5 ▼]   [NJ] |
+--------------+----------------------------------------------+----------------+
| Conversations|                                              | Context        |
|              |  Apr 23 · Weekly exec digest                 |                |
| + New chat   |  ─────────────────────────────────────       | Connected (9)  |
|              |                                              |  • Anthropic ✓ |
| Today        |  You:  how much on claude last week          |  • OpenAI   ✓  |
| · Claude vs  |  ──────                                      |  • Gemini   ✓  |
|   GPT in Apr |                                              |  • Snowflake✓  |
| · Cursor     |  Agent: You spent $4,812 on Anthropic...     |  • dbt Cloud✓  |
|   overshoot  |  [ stacked bar chart ]                       |  • BigQuery — |
| This week    |  [ table: model × cost × delta ]             |  • Cursor   ✓  |
| · Snowflake  |  Sources: 1,847 Anthropic invoices lines,    |  • AWS      ✓  |
|   auto-      |  Mar 1 - 21. Data as of 12m ago. 98% cov.    |  • Airflow  — |
|   suspend    |                                              |                |
| · dbt top10  |  Follow-ups:                                 | Time range     |
| Older        |  [ Drill into Opus ] [ vs last week ]        | Mar 1 – Mar 31 |
| · Q1 review  |  [ Save as report ] [ Set a budget ]         | Sticky ✓       |
|              |                                              |                |
|              |  ─────────────────────────────────────       | Budget state   |
|              |                                              |  AI:  $8.2K /  |
|              |  You: compare to gpt-4o for the same period  |       $10K     |
|              |  [ streaming... ]                            |  ▓▓▓▓▓▓▓░░     |
|              |                                              |  82% of month  |
|              |                                              |                |
|              |                                              | [ collapse » ] |
+--------------+----------------------------------------------+----------------+
| [/] commands   [@] platforms   [#] reports   [📎] attach   [↑] send          |
+------------------------------------------------------------------------------+
```

### 1.2 Columns

**Left rail — Conversations (240px, collapsible to 56px icon rail).**
- "New chat" button pinned at top. `Cmd/Ctrl + N` keyboard shortcut. Matches Cursor's New Chat affordance.
- Search box (`Cmd/Ctrl + K` focuses it).
- Conversations grouped by recency: **Today**, **Yesterday**, **This week**, **This month**, **Older**. Each group is collapsible. Model: Cursor and Linear both use this grouping — see [linear.app/changelog/2024-08-22-linear-ai](https://linear.app/changelog).
- Row shows title (auto-generated from first user message), first-emoji-or-platform-icon prefix, and a right-side timestamp on hover.
- Right-click / long-press: Rename, Pin to top, Duplicate, Share, Delete.
- Pinned conversations live in a separate "Pinned" section above Today.
- Hovering a row previews the last assistant message in a tooltip (Arc-style).

**Main pane — Message stream (fluid, min 640px).**
- Full-height scroll area. Top anchored to the composer at the bottom.
- Each message is a *block*, not a bubble. User blocks are a soft grey card right-aligned with a 70% max width; assistant blocks are a full-width card with no left rail so charts/tables can breathe. This matches Claude.ai's artifact-style wide responses and v0's generative UI blocks.
- Sticky header inside the pane shows the conversation title (editable inline, Linear-style) and a small breadcrumb of the effective time range and platform filter.
- A faint "Jump to latest" pill appears when user scrolls up.

**Right rail — Context panel (320px, collapsible to 0).**
- Three stacked cards:
  1. **Connected platforms**: each row is `icon · name · status dot · last sync`. Click opens the connector settings drawer. Missing/misconfigured connectors show an amber dot with "Fix" link.
  2. **Time range**: the conversation-scoped range. Shows a small month calendar strip with draggable handles. A toggle "Sticky across turns" (default on).
  3. **Budget state**: the active budget for the effective scope (team or workspace). Progress bar, monthly burn rate, days remaining, and a "View budgets" link.
- User can collapse the rail via `]` (keyboard) or the `»` button. State persists per user in `localStorage` and on the server.

**Top bar (56px).**
- Left: product logo + workspace switcher.
- Center: current conversation title + inline rename.
- Right, left-to-right: `New chat`, `Share`, `Time range selector`, `Model selector` (Claude 4.7 / Claude 4.5 / Haiku — with cost-per-answer hint), avatar/menu.
- The time-range selector here *scopes the entire conversation*. Changing it announces the change in the stream as a system chip: `Time range changed: Mar 1–31 → Apr 1–23 (affects all subsequent turns)`.

### 1.3 Mobile (single column, <768px)

- Main pane fills the viewport. Left and right rails become full-screen sheets behind swipe-from-edge gestures (Arc-style). The bottom-nav has three tabs: **Chats** (left rail), **Thread** (main), **Context** (right rail).
- Composer uses the native keyboard's toolbar and exposes the `/ @ #` triggers as a horizontal chip strip directly above the text input.
- Tables degrade to a horizontally-scrollable card list; charts render at 100% width with a 3:2 ratio.

---

## 2. Message composition

The composer sits in a sticky footer, minimum 88px tall, growing to a max of 40% viewport height as the user types. Submit on `Enter`, newline on `Shift+Enter`, matching Claude.ai.

### 2.1 Empty state

When a conversation has zero turns, the composer is centered in the main pane (not docked), with:
- A hero headline: *"Ask anything about your AI and data platform spend."*
- Four suggested-prompt chips in a 2×2 grid, seeded from the user's connected platforms:
  - "What did we spend on Claude last week?"
  - "Which dbt models cost the most this month?"
  - "Find Snowflake warehouses that never auto-suspend"
  - "Compare Cursor license cost vs seat utilization"
- A small "Browse examples" link that opens the example library (see §8.4).

Once the first message is sent, the composer animates to the docked-footer position (200ms ease-out).

### 2.2 Inline triggers

- **`/` — command palette.** Opens an inline dropdown with:
  - *Saved queries* (user's saved prompts)
  - *Library templates* (`/weekly-exec`, `/top-dbt-waste`, `/anomaly-scan`)
  - *Actions* (`/clear`, `/rename`, `/export`, `/share`, `/new-chat`)
  - Keyboard: arrow keys navigate, Enter selects, Esc dismisses. Inspired by Linear's command palette.

- **`@` — platform mentions.** Typing `@` lists connected platforms with icons. Selecting `@anthropic` inserts a pill that *scopes all tool calls in this turn* to that platform. Multi-select is allowed (`@anthropic @openai`). The pill is removable with Backspace.

- **`#` — saved report templates.** Injects a parameterized report (e.g., `#weekly-exec-summary`). Each template is a multi-step prompt that the agent expands server-side. Variables (team, time range) are filled from context or prompted inline.

- **`!` — focus a specific tool.** Power-user affordance. `!snowflake.query_history` forces the agent to call that one tool. Useful for demos and eval baselining.

### 2.3 Attachments

Paperclip opens a picker for:
- CSV of queries/traces — the agent ingests and references rows in its answer.
- A previous Costly report (PDF/markdown) — the agent uses it as context.
- A raw Snowflake/BigQuery query — the agent explains cost and optimization.

Max 10MB, client-side virus-scan via WebAssembly ClamAV stub, then a signed POST to `/api/chat/uploads`.

### 2.4 Drafts and offline

Every keystroke autosaves to `localStorage` keyed by conversation id. A "Draft saved" indicator appears top-right of the composer. If the user closes the tab mid-stream, reopening restores both the in-flight assistant message (via SSE reconnect) and the composer draft.

---

## 3. Response anatomy

Every assistant turn is a composed block. The block has a predictable top-to-bottom structure so the eye knows where to look.

### 3.1 Structural order

```
+--------------------------------------------------------------+
| [ Tool chips — collapsed by default ]                        |
| anthropic.get_usage_report · snowflake.query_history · +1    |
+--------------------------------------------------------------+
| Streaming text answer...                                     |
|                                                              |
| Key number callouts: $4,812 (Anthropic, Mar 1-21)            |
|                                                              |
+--------------------------------------------------------------+
| [ Chart block — stacked bar, line, or gauge ]                |
+--------------------------------------------------------------+
| [ Table block — sortable, filterable, exportable ]           |
+--------------------------------------------------------------+
| Citations: 1,847 Anthropic invoice lines · 3 Snowflake QH    |
| rows · based on [org_spend_daily] materialized at 12:04 UTC  |
+--------------------------------------------------------------+
| Freshness: 12m ago · Coverage: 98% · Answer cost: $0.023     |
+--------------------------------------------------------------+
| [ Follow-up chips ]                                          |
+--------------------------------------------------------------+
| [ Thumbs up / down · Share this answer · Pin as widget ]     |
+--------------------------------------------------------------+
```

### 3.2 Streaming

- Server-sent events stream text, tool-call events, and chart/table payloads interleaved. The client state machine (Zustand + custom reducer) dispatches events into three slots: `text`, `tool_calls`, `artifacts`.
- Tokens render with a 1-frame shimmer at the caret, matching Claude.ai.
- Charts/tables appear placeholder-first (skeleton loader), then swap to the final render when the payload arrives. Matches v0's generative UI staging.

### 3.3 Inline charts

Chart blocks are produced by the agent emitting a structured `chart` artifact:

```jsonc
{
  "type": "chart",
  "kind": "stacked_bar",      // stacked_bar | line | area | gauge | sankey | waterfall
  "title": "Anthropic spend by model, Mar 1-21",
  "xAxis": { "field": "date", "type": "time" },
  "yAxis": { "field": "usd", "type": "money", "currency": "USD" },
  "series": [
    { "name": "Opus 4.5",   "color": "anthropic.opus",   "data": [...] },
    { "name": "Sonnet 4.7", "color": "anthropic.sonnet", "data": [...] }
  ],
  "annotations": [
    { "x": "2026-03-14", "label": "Spike: batch eval run" }
  ],
  "sourceRef": "anthropic.get_usage_report#call_42"
}
```

Rendering uses Recharts under the hood with a thin adapter layer. Click any series point to open a drill-down sheet that shows the underlying rows. Hover shows the exact value, the source tool call, and freshness.

Supported `kind` values in v1: `stacked_bar`, `line`, `gauge`, `table-spark`. v2: `area`, `sankey` (for flow across platforms), `waterfall` (month-over-month deltas).

### 3.4 Tables

- Sortable columns (click header), multi-column sort with `Shift+click`.
- Per-column filter via a chevron menu (contains, equals, >, <, between).
- Sticky header and first column.
- Row-level actions on hover: "Drill in", "Copy row", "Open in Snowflake".
- Export: CSV, TSV, JSON, Markdown. Copy-to-clipboard in Slack-friendly format.
- Pagination kicks in at 200 rows; virtual scroll for >1000.

### 3.5 Citations (Perplexity-style)

Every numeric claim in the assistant's text is linked to a *source pill*. Hovering shows the tool call name, the exact row count, the materialized-view timestamp, and a "View rows" action. Clicking opens a side drawer with the raw rows.

Example rendered text:

> You spent $4,812<sup>[1]</sup> on Anthropic between Mar 1–21, up 34%<sup>[2]</sup> vs the prior 21 days.

Hovering `[1]` shows: *`anthropic.get_usage_report` → 1,847 invoice lines → cached 12m ago → 98% coverage*.

This mirrors Perplexity's inline citations ([perplexity.ai](https://perplexity.ai)) and Stripe Sigma's "Based on N rows" footers ([stripe.com/sigma](https://stripe.com/sigma)).

### 3.6 Tool-call transparency

A collapsible strip at the top of each assistant block:

```
▸ Used 3 tools · 2.1s · $0.023
```

Expanded:

```
▾ Used 3 tools · 2.1s · $0.023

   1. anthropic.get_usage_report            0.6s   ok
      args: { start: "2026-03-01", end: "2026-03-21", granularity: "day" }
      result: 21 rows, $4,812.41 total
      [ view raw ]

   2. snowflake.query_history               1.2s   ok
      args: { start: ..., tags: ["llm_trace"] }
      result: 1,847 rows, $312.55 in compute
      [ view raw ]

   3. org_spend_daily.read (cache)          0.1s   hit
      result: served from materialized view (12 min old)
```

This is modeled directly on LangSmith ([smith.langchain.com](https://smith.langchain.com)), Langfuse traces ([langfuse.com/docs/tracing](https://langfuse.com/docs/tracing)), Helicone session view ([helicone.ai](https://helicone.ai)), and Arize Phoenix ([phoenix.arize.com](https://phoenix.arize.com)). Each tool row is expandable to show args and truncated results; "view raw" opens a full trace in a drawer with JSON viewer, timing waterfall, and a "Replay" button.

### 3.7 Confidence and freshness

A single-line footer sits above the follow-up chips:

```
Data as of 12 min ago · Coverage 98% · Confidence: high
```

- **Freshness**: max of `now - min(tool_freshness)` across tool calls. Red/amber/green dot based on thresholds (<1h green, 1–24h amber, >24h red).
- **Coverage**: the % of in-scope platforms that actually returned data (if the user asked about "all AI spend" but only 9 of 10 connectors returned, coverage is 90%).
- **Confidence**: qualitative label from the agent. Hover shows why (e.g., "High: used exact invoice numbers. One estimate used for Gemini token prices — see tooltip.").

### 3.8 Cost of the answer

Every assistant block shows the literal cost of generating that answer ("This answer cost $0.023"). Costly pitching Costly. The number is computed server-side from the actual Anthropic/OpenAI usage for this turn including tool-call loops and is cached with the message. Hover to expand:

```
Answer cost: $0.023
  Claude 4.5 Sonnet input:  3,214 tokens → $0.0096
  Claude 4.5 Sonnet output:   812 tokens → $0.0122
  Tool-call overhead:        21 calls    → $0.0012
  Cached reads:              2 hits      → save $0.0081
```

### 3.9 Empty / error states per block

- **Tool failed**: red pill `1 tool failed — anthropic.get_usage_report (401)` with "Fix connector" link.
- **Partial**: amber pill `1 of 3 tools timed out`.
- **No data**: soft grey "No data in this range. Try expanding to 90 days." with a one-click time-range expand button.

---

## 4. Follow-up interactions

Under every assistant block is a chip row of suggested follow-ups. The agent returns up to 6 chips per turn, grouped into three kinds:

- **Drill-down** (lens icon): "Drill into Opus spend", "Show which team drove the spike".
- **Compare** (scale icon): "Compare to last week", "vs same period last year".
- **Act** (bolt icon): "Save as report", "Set a budget", "Open a GitHub PR", "Pin as widget".

### 4.1 Save as report

Clicking "Save as report" opens a modal:

```
+------------------------------------------------+
| Save as scheduled report                       |
| ---------------------------------------------- |
| Title: Weekly AI spend digest                  |
| Prompt: <auto-filled from this turn>           |
|                                                |
| Cadence: ( ) Daily  (•) Weekly  ( ) Monthly    |
| Day of week: Mon                               |
| Time: 08:00 America/Toronto                    |
|                                                |
| Deliver to:                                    |
|  [x] Slack #finance  (webhook configured)      |
|  [ ] Email exec@foo.com                        |
|  [ ] Teams                                     |
|                                                |
| Variables:                                     |
|  time_range: rolling 7d                        |
|  team:       all                               |
|  budget:     ai-monthly                        |
|                                                |
|           [ Cancel ]   [ Save & schedule ]     |
+------------------------------------------------+
```

On save, the conversation's tool-call graph is pinned — i.e., the report always runs the same tools with the same prompt, substituting variables. This guarantees reproducibility even as the agent's system prompt evolves. See §8 for scheduling mechanics.

### 4.2 Set a budget

Opens a budget-creation modal with scope (platform / team / workspace), period, threshold, and notification rules. The budget name, threshold, and scope are prefilled from the conversation context (e.g., if the user was discussing Anthropic, the modal defaults to "Anthropic monthly budget").

### 4.3 Open a GitHub PR

For a curated set of *actionable recommendations*, the agent can one-click open a PR:

- `warehouse_auto_suspend`: detect Snowflake warehouses with `AUTO_SUSPEND > 600` and propose a Terraform/SQL patch.
- `dbt_model_tags`: add tags to high-cost dbt models for better routing.
- `claude_model_downgrade`: replace `claude-opus-*` with `claude-sonnet-*` in a specific code path after proving the latency/quality trade.
- `openai_json_mode`: switch to Structured Outputs where output is already JSON-parsed.

Flow:
1. User clicks "Open a GitHub PR".
2. Modal shows the planned diff (read-only), target repo (from a connected list), branch name (`costly/auto-suspend-fix-20260423`), and commit message.
3. User confirms; Costly's GitHub App opens the PR and returns the PR URL as a chip in the thread: `PR opened → #1284`.
4. The chat message is updated with a "PR status" live chip that tracks merge status via webhook.

### 4.4 Pin as dashboard widget

Any chart or table can be pinned to a dashboard page. Pinning clones the artifact, captures its sourceRef (tool call + args), and registers it as a widget that re-runs on a cron (default: match the conversation's time range with a rolling window). Widgets live at `/dashboards/:id` and are draggable.

---

## 5. Multi-turn context

### 5.1 Sticky scope

The following are sticky across turns within a single conversation unless the user explicitly changes them:
- **Time range** (set via top bar or in the right rail).
- **Platform filter** (last `@` mention set).
- **Team scope** (if the user said "for the data team").
- **Currency** and locale.

Each sticky value shows as a chip in the conversation's sticky header. Clicking the chip lets the user change or clear it. When changed, a system message chip appears in the stream: `Scope changed: time range → Apr 1–23`.

### 5.2 Drill memory

The agent maintains an explicit *focus stack* per conversation: the most recent platform, model, and cost dimension the user was exploring. When the user says "drill into that", the agent resolves `that` against the top of the stack. This avoids the Perplexity-style "what did you mean" ambiguity.

### 5.3 Deep-research subagent hand-off

For heavy questions ("investigate why dbt costs doubled this week across all warehouses"), the main agent spawns a subagent and renders a *progress card* in the stream:

```
+--------------------------------------------------------------+
| ⚙ Deep investigation: dbt cost anomaly (2m 14s elapsed)      |
|                                                              |
|  [■■■■■■□□□□]  Step 3 of 5                                    |
|                                                              |
|  ✓ Pulled last 30d dbt Cloud usage                           |
|  ✓ Correlated with Snowflake QH                              |
|  ▸ Comparing to last 4 weeks baseline                        |
|  · Hypothesis scoring                                        |
|  · Draft final answer                                        |
|                                                              |
|  [ Collapse — run in background ]    [ Stop ]                |
+--------------------------------------------------------------+
```

- Collapse minimizes to a small chip in the bottom-right of the viewport; a toast fires when the subagent completes.
- The user can keep chatting in the same thread while the subagent runs — new turns queue behind the subagent's final output or (optionally) interleave based on a toggle.
- The subagent's intermediate tool calls stream into a separate "Investigation" drawer so the main thread stays readable.

This pattern follows Arc's "Browse for Me" ([arc.net/max](https://arc.net/max)) and Claude's research mode.

---

## 6. Safety and trust

### 6.1 Estimated values

When the agent falls back to estimated prices (e.g., Gemini token price before official invoices land), the rendered number is decorated:

```
$812.40 ≈
```

A subscript `≈` and a light-grey background. Hover tooltip:

> Estimated: no invoice yet for this period. Using list price $0.00025/1K in, $0.00075/1K out. Override in **Settings → Custom pricing**.

Numbers exported to CSV/markdown include an `estimated=true` column so downstream consumers can filter.

### 6.2 Stale data banner

If any tool's freshness exceeds 24h, a dismissible banner appears at the top of the assistant block:

```
⚠ Some data is stale — Anthropic usage last synced 31h ago. [ Resync now ]
```

Clicking "Resync now" triggers the connector's sync and re-runs the turn when finished.

### 6.3 Misconfigured connector

If a required connector is disconnected or misconfigured mid-answer, the affected numbers are blanked with a `—` and a red chip appears:

```
✗ Gemini connector: service account key expired. [ Fix now ]
```

The "Fix now" link opens the connector settings drawer with the exact error surfaced.

### 6.4 PII and query redaction

All raw SQL and trace payloads are routed through a server-side redactor before rendering. Email addresses, API keys, and phone numbers are masked in the UI and raw drawer alike. A "Show original" toggle exists for workspace admins only.

### 6.5 Destructive actions

Any action that writes to a user system (GitHub PR open, budget creation, connector reconfigure) requires a second click in a modal with a clear preview. No silent side effects.

---

## 7. Shareable artifacts

### 7.1 Public share link

Clicking "Share" on a conversation or a single answer opens:

```
+--------------------------------------------------+
| Share this answer                                |
| ------------------------------------------------ |
| Link: https://costly.cdatainsights.com/s/ab12… │
|                                                  |
| Visibility:                                      |
|  (•) Anyone with the link                        |
|  ( ) Workspace members only                      |
|                                                  |
| Options:                                         |
|  [x] Anonymize company names and dollar amounts  |
|  [x] Strip tool-call args                        |
|  [ ] Require email sign-in                       |
|                                                  |
| Expires: ( ) Never (•) In 7 days ( ) In 30 days  |
|                                                  |
| [ Copy link ]  [ Embed ]  [ Export ]             |
+--------------------------------------------------+
```

Anonymized mode replaces dollar amounts with index values (`$100 → 1.0x`) and company/project names with pseudonyms. This is how a prospect shares a Costly answer externally without leaking numbers.

### 7.2 Embed snippet

A Notion- and Slack-friendly embed URL that renders a read-only version of the answer. Notion auto-embeds it via OEmbed; Slack unfurls with Open Graph metadata showing the headline number and a chart thumbnail.

### 7.3 Export

- **Markdown**: full answer with charts rendered as linked PNGs and tables as GFM tables.
- **PDF**: page-broken, branded Costly header/footer, cover page with conversation metadata.
- **PPTX** (v2): each chart becomes a slide.

Export respects anonymization if enabled.

---

## 8. Saved queries and scheduled reports

### 8.1 Data model

```
SavedQuery {
  id, workspace_id, author_id, title, prompt_template,
  variables: [{ name, type, default }],
  pinned_tool_plan: [{ tool, args_template }],
  created_from_message_id
}

ScheduledReport {
  id, saved_query_id, cadence (RRULE), next_run_at,
  deliveries: [{ kind: slack|email|teams, target }],
  last_run: { at, status, answer_id }
}
```

### 8.2 Variables

Supported variable types: `time_range`, `team`, `budget`, `platform`, `string`, `enum`. Variables interpolate into the prompt with `{{ }}` syntax and can be overridden at send-time (via the `/` palette) or at schedule-time.

### 8.3 Delivery

- **Slack** via incoming webhook per channel. Report renders as a Block Kit message: headline number, a mini chart image (server-rendered via Recharts + satori), and a "View full answer" button linking back to the Costly share URL.
- **Email** via Postmark. HTML email with inline charts.
- **Teams** via incoming webhook and Adaptive Cards.

### 8.4 Example library (ship 20 pre-installed)

Each workspace starts with 20 curated saved queries, discoverable via `/` palette and a dedicated "Library" page:

1. Weekly AI spend exec digest
2. Top 10 expensive dbt models this week
3. Snowflake warehouses without auto-suspend
4. Claude vs GPT head-to-head by use case
5. Budget status across all platforms
6. Anomaly scan — last 7 days, all platforms
7. Per-team AI spend breakdown
8. Cursor seat utilization vs license cost
9. Month-over-month delta by platform
10. Top 20 expensive Snowflake queries
11. Cache-hit-rate audit (Anthropic + OpenAI)
12. Prompt-caching opportunity finder
13. Idle BigQuery reservations
14. Fivetran connector cost ranking
15. dbt models without tags
16. GitHub Copilot vs Cursor comparison
17. Off-peak warehouse usage check
18. AI spend forecast — end-of-month
19. Model-downgrade candidates (Opus→Sonnet)
20. Onboarding health — connector freshness map

### 8.5 Turning a conversation into a report

A conversation is a *draft*. When the user hits "Save as report", the system captures:
- The latest assistant block's prompt (user's final turn).
- The pinned tool plan (which tools, with what arg templates) — not the *exact* args, so the report re-runs live each schedule.
- The rendering template (chart kinds, table columns).
- The delivery targets and variables.

Reports are idempotent: running the same report twice in the same hour returns the cached result with a freshness timestamp, not a new LLM call.

---

## 9. Cost-of-agent controls

Costly runs on Anthropic/OpenAI, so the agent itself costs money. We expose controls directly in the UI:

### 9.1 Per-user token budget

In workspace settings, an admin sets a monthly *agent token budget* per user (default: $20/user/month). The right rail budget card has a second progress bar for "Agent usage this month". On 80% burn, the user sees an inline warning in the composer. On 100%, the composer disables with a clear "Admin can raise your limit" message.

### 9.2 Cached-response reuse

- Every assistant turn is hashed by `(prompt_template, tool_plan, resolved_args, data_freshness_bucket)`.
- Hits within 15 minutes return the cached answer *instantly* and are rendered with a subtle "Served from cache (12m old)" chip. The user can force a re-run with a refresh button.
- Cached answers still cost nothing to serve and are counted as $0.00 in the cost-of-answer line.

### 9.3 Smaller-model toggle

Top-bar model selector (default: Claude 4.5 Sonnet) lets the user pick:
- **Claude 4.7 / Sonnet** — default, best quality.
- **Claude Haiku 4.5** — 3x cheaper, 90% quality for most queries. A tooltip explains: "Good for quick lookups. For exec-grade reports, use Sonnet."
- **Auto** (v2) — the agent picks per turn based on a routing heuristic.

Choosing a smaller model updates the "Answer cost" display prospectively ("next answer ≈ $0.008").

### 9.4 Tool-call cap

Per-turn hard cap of N tool calls (default 12; admin-configurable). When hit, the agent halts and renders a partial answer with a "Continue" button that grants another N calls.

---

## 10. Quality and eval loop

### 10.1 Inline feedback

Every assistant block has `👍 / 👎` buttons. Clicking 👎 opens a small popover:

```
What went wrong?
( ) Wrong number
( ) Missing data
( ) Misinterpreted question
( ) Bad chart / format
( ) Too slow
( ) Other

Tell us more (optional): [_______________________]

[ Send feedback ]
```

Feedback is stored against the message id, the tool trace, and the prompt version. A `/admin/evals` page shows thumbs-down aggregates by prompt version, tool, and topic.

### 10.2 Canary eval set

A hand-curated set of ~40 standard questions (the "golden set") lives in `backend/evals/golden/*.yaml`. Each entry:

```yaml
id: golden.weekly-anthropic
prompt: "How much did we spend on Claude last week?"
fixtures:
  - anthropic.fixture_march_2026
  - snowflake.fixture_march_2026
expectations:
  - number_match: { value_usd: 4812.41, tolerance_pct: 2 }
  - tool_called: anthropic.get_usage_report
  - chart_kind: stacked_bar
  - latency_ms_max: 8000
  - cost_usd_max: 0.05
```

The eval harness runs on every prompt/tool change in CI. Regressions block merge. Results surface in a `/admin/evals/runs/:id` page and in Slack via a webhook.

### 10.3 Per-turn self-critique (v2)

Before streaming the final answer, an optional second LLM pass checks the draft for:
- Numbers consistent with tool outputs.
- Every dollar figure cited.
- No hallucinated platform names.

Critique failures trigger a silent retry once; if the retry also fails, the answer is rendered with an amber "Low confidence" badge and flagged in the eval dashboard.

---

## 11. Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Cmd/Ctrl + N` | New chat |
| `Cmd/Ctrl + K` | Focus search in left rail |
| `Cmd/Ctrl + /` | Open command palette |
| `Cmd/Ctrl + Enter` | Send message |
| `Shift + Enter` | Newline |
| `Cmd/Ctrl + Shift + P` | Open platform-mention picker |
| `[` | Toggle left rail |
| `]` | Toggle right rail |
| `Cmd/Ctrl + S` | Save as report |
| `Cmd/Ctrl + Shift + S` | Share |
| `Cmd/Ctrl + E` | Export current answer |
| `J` / `K` | Next / previous message (when focused on stream) |
| `R` | Re-run the focused assistant answer |
| `Esc` | Close any open popover/drawer |

Shortcuts are discoverable via a `?` overlay, Linear-style.

---

## 12. Accessibility

- WCAG 2.1 AA across the entire surface.
- All interactive chips are real `<button>` elements with proper `aria-label`.
- Streaming text uses `aria-live="polite"` on a dedicated region; chart deltas announce "Chart updated: Anthropic spend by model".
- Contrast ratio ≥4.5:1 for all text. Amber/red/green dots also use shape redundancy (dot vs triangle vs check).
- Keyboard-only navigation verified end-to-end including the chart drill-downs.
- Screen-reader text for every chart: a `<desc>` with a one-sentence summary and a linked "View as table" affordance.

---

## 13. Performance targets

- Composer input-to-first-token ≤ 1.5s p50, ≤ 3s p95.
- Conversation list initial render ≤ 200ms p95 (from a local cache of last 50 conversations).
- Chart artifact render ≤ 150ms after payload arrival.
- No layout shift (CLS ≤ 0.05) when streaming completes.
- 60fps scroll in the main pane up to 300 messages; above that, virtualize.

Measurement: Vercel Speed Insights + Sentry session replays + a custom `/api/chat/metrics` endpoint that ingests client-reported timings keyed by message id.

---

## 14. Telemetry (opt-in, workspace-level)

Every significant event is logged with the message id, user id (hashed), and workspace id:
- `chat.message.sent`
- `chat.answer.streamed` (with time-to-first-token, total-time, tool-count, answer-cost-usd)
- `chat.answer.feedback` (thumbs, reason, note)
- `chat.followup.clicked`
- `chat.report.saved`
- `chat.share.created`
- `chat.pr.opened`
- `chat.subagent.spawned` / `completed`

Data lands in the Costly analytics warehouse and feeds into:
- A PostHog-style funnel dashboard (see [posthog.com/docs/llm-analytics](https://posthog.com/docs/llm-analytics)).
- The eval loop.
- Per-workspace health reports.

---

## 15. API / backend contract (selected)

### 15.1 Stream a turn

```
POST /api/chat/:conversationId/messages
Content-Type: application/json
Accept: text/event-stream

{ "content": "how much on claude last week", "model": "claude-4.5-sonnet", "scope": { "timeRange": "last_7d", "platforms": ["anthropic"] } }
```

SSE event types:
- `text` — token deltas
- `tool_call_start` — `{ id, name, args }`
- `tool_call_end` — `{ id, durationMs, status, resultSummary }`
- `artifact` — a chart or table payload
- `citation` — `{ id, sourceRef, rowCount, freshness }`
- `followup` — chip definitions
- `final` — `{ answerId, costUsd, confidence, freshness, coveragePct }`
- `error` — actionable error

### 15.2 Conversation list

```
GET /api/chat/conversations?group=today,this_week,older&limit=50
```

Returns a grouped, paginated list. ETag + `If-None-Match` for fast revalidation.

### 15.3 Saved query + schedule

```
POST /api/saved-queries
POST /api/saved-queries/:id/schedules
```

### 15.4 Share link

```
POST /api/chat/messages/:id/share
{ "visibility": "public", "anonymize": true, "expiresInDays": 7 }
→ { "url": "https://costly.cdatainsights.com/s/ab12cd34" }
```

---

## 16. Visual design notes

- Type: Inter for UI, JetBrains Mono for code/query blocks.
- Spacing scale: 4 / 8 / 12 / 16 / 24 / 32 / 48.
- Border radius: 12px for cards, 8px for chips, 6px for inputs.
- Color: neutral 50 → 900 scale, plus per-platform brand accents used sparingly (Anthropic orange, OpenAI green, Gemini blue, Snowflake cyan, etc.).
- Dark mode is the default. Light mode is supported; the bar for looks-great in both modes is non-negotiable.
- Motion: 150–250ms ease-out for UI state; 1 frame shimmer on streaming caret; no bouncy springs.

---

## 17. Implementation phases

### v1 (ship in 3 weeks, scope to prove the UX)

Must-haves:
- Three-column layout with collapsible rails and sticky top bar.
- Left rail with Today/This week/Older grouping, search, rename, pin, delete.
- Main pane with streaming text, tool-call transparency strip, inline charts (`stacked_bar`, `line`, `gauge`, `table-spark`), sortable tables, Perplexity-style citations, freshness/confidence/answer-cost footer.
- Composer with `/`, `@`, `#` triggers, suggested-prompt chips on empty state, file attach.
- Right rail with Connected Platforms, Time Range, Budget State.
- Top-bar new chat, share (public link with anonymize toggle), time-range selector, model selector.
- Follow-up chips: drill, compare, save-as-report, set-a-budget, pin-as-widget.
- Sticky time-range and platform scope across turns.
- Thumbs up/down with reason popover.
- 10 example-library saved queries pre-installed.
- Keyboard shortcuts (`Cmd+N`, `Cmd+K`, `Cmd+/`, `J/K`, `[`, `]`).
- Estimated-value decoration and stale-data banner.
- Mobile: single column with swipe rails.
- SSE streaming API and conversation-list API.

Deferred to v2:
- Deep-research subagent with progress card.
- Open-a-GitHub-PR flow.
- Embed snippets (Notion/Slack OEmbed).
- Teams delivery for scheduled reports.
- Cache-hit surface and force-refresh.
- Smaller-model "Auto" routing.
- Self-critique second pass.
- Sankey and waterfall chart kinds.
- PPTX export.
- Eval-harness dashboard UI (CLI only in v1).

### v2 (next 4–6 weeks)

- Deep-research subagent, progress card, background runs, interleaved turns.
- GitHub App + supported PR templates (warehouse auto-suspend, dbt tags, model-downgrade, OpenAI structured outputs).
- Notion/Slack OEmbed, Teams webhook delivery.
- Smaller-model auto routing with heuristic + cost/quality guard rails.
- Self-critique pass with low-confidence flagging.
- Per-turn hard cap on tool calls, with "Continue" flow.
- Sankey, waterfall charts; chart drill-down drawer.
- Full eval dashboard UI at `/admin/evals`.
- PPTX export.
- Public shared-answer page with embedded read-only experience.
- 20-query example library complete (fill remaining 10).

### v3 (stretch, post-YC-ready)

- Multiplayer mode: two users in the same conversation, presence cursors à la Linear and Arc.
- Agent memory across conversations ("last time you asked about dbt cost, I suggested adding tags — has that landed?").
- API-first: a `POST /v1/ask` external endpoint so customers can embed the agent in their own tooling.
- In-product A/B testing of prompt versions with automatic rollback on eval regression.
- Cost-per-insight ROI dashboard: show customers what Costly has saved them vs what it cost to run.

---

## 18. Open questions

1. **Left rail folders.** Do we ship manual folders in v1 or lean on auto-grouping + pin-to-top? *Proposal: skip folders in v1, revisit if top-10 workspaces ask.*
2. **Conversation forking.** Should "Regenerate from here" create a branch or overwrite? *Proposal: branch, shown as a switcher in the stream.*
3. **Multi-workspace users.** Do we show cross-workspace conversations in the left rail? *Proposal: no, workspace-scoped only; use the top-left workspace switcher.*
4. **Agent pricing passthrough.** Do we charge customers per-answer-cost or bundle into seats? *Orthogonal to UX, but the surface already supports both via the cost-of-answer display.*
5. **Public share indexing.** Should public share pages be `noindex` by default? *Proposal: yes, with an opt-in toggle for case-study-grade pages.*

---

## 19. References and further reading

- Cursor chat UX — [cursor.com](https://cursor.com), [cursor.com/docs](https://cursor.com/docs)
- Linear AI and changelog — [linear.app/changelog](https://linear.app/changelog)
- Arc browser Max / Browse for Me — [arc.net/max](https://arc.net/max)
- Vercel v0 generative UI — [v0.dev](https://v0.dev), [vercel.com/blog/announcing-v0](https://vercel.com/blog/announcing-v0)
- Perplexity citations and follow-ups — [perplexity.ai](https://perplexity.ai)
- Claude.ai composer and artifacts — [claude.ai](https://claude.ai), [anthropic.com/news/artifacts](https://www.anthropic.com/news/artifacts)
- Stripe Sigma AI assistant — [stripe.com/sigma](https://stripe.com/sigma), [stripe.com/blog/sigma-ai](https://stripe.com/blog)
- Supabase SQL assistant — [supabase.com/blog/sql-editor-ai-assistant-v2](https://supabase.com/blog)
- LangSmith tool-call traces — [smith.langchain.com](https://smith.langchain.com), [docs.smith.langchain.com](https://docs.smith.langchain.com)
- PostHog LLM analytics — [posthog.com/docs/llm-analytics](https://posthog.com/docs/llm-analytics)
- Langfuse tracing — [langfuse.com/docs/tracing](https://langfuse.com/docs/tracing)
- Helicone sessions — [helicone.ai](https://helicone.ai)
- Arize Phoenix — [phoenix.arize.com](https://phoenix.arize.com), [docs.arize.com/phoenix](https://docs.arize.com/phoenix)

---

*End of spec. Feedback welcome in-line via PR review or as a Costly conversation — eat the dog food.*
