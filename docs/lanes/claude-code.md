# Lane: Claude Code Connector

One significant capability per pass. Grade progression tracked below.

## Status

**Current grade: B+** (up from B — per-tool-call attribution shipped 2026-04-24).

Matches ccusage core math, with an added YC-pitch differentiator: no OSS
tool (ccusage, agentsview, sniffly, CCMeter, Maciek-roboblog) emits per-
tool-call cost attribution as a first-class field on the cost record.

## Shipped

- 2026-04-24 — **Per-tool-call cost attribution**: parses
  `message.content[].type == "tool_use"` blocks, splits output tokens +
  cost by JSON-serialised block weight, emits
  `metadata.tool_breakdown` keyed by tool name with `{calls,
  output_tokens, cost_usd, is_mcp, is_builtin}`. Also emits
  `metadata.tool_calls_total`. Flags MCP tools
  (`name.startswith("mcp__")`) and tags built-in Claude Code tools
  (Bash/Read/Edit/Write/Glob/Grep/WebFetch/WebSearch/NotebookEdit/
  TodoWrite/Task/Skill). 22 new tests.

## Backlog (ordered by impact / YC-pitch unlock)

1. **5-hour rolling block analytics** — Anthropic Max quota is measured
   in 5-hour windows. Emit per-block rollups and a `/api/claude-code/blocks`
   endpoint. ccusage's `blocks` command is the reference. Unlocks "you
   are 80% through your 5h Max quota" alerts.
2. **Rate-limit quota awareness** — Max plan = 900 requests / 5hr (900
   turns). Track `parentUuid`-linked chains as a single request; emit a
   `remaining_quota` hint per block.
3. **Multi-machine aggregation** — laptop + desktop = same user. Either
   a ship-to-backend daemon, an rsync target, or an OTEL collector
   (CLAUDE_CODE_ENABLE_TELEMETRY=1). Today each machine is an island.
4. **`requestId` dedup** — retries emit the same `requestId`. CCMeter
   and ccusage both dedupe on it. ~10 LOC hash set.
5. **Conversation replay UI backend** — expose `/api/claude-code/sessions/
   {session_id}` returning every turn in order (role, content, tool_use,
   tool_result) so the frontend can render a readable session replay.
6. **`sessionId` + `gitBranch` metadata** — already parsed, not yet
   surfaced on the `UnifiedCost` record. Cheap wins for the drill-down
   view.
7. **Subagent (`parentUuid`) attribution** — label turns as user-initiated
   vs delegated (Task / Skill spawn). Important in the agents-calling-
   agents era.
8. **LiteLLM pricing sync** — nightly fetch of
   `model_prices_and_context_window.json`; graceful fallback to hard-coded
   table if the fetch fails. Stops us from drifting on new models.
9. **Opus 4.7 tokenizer uplift banner** — flag projects with >20% of
   tokens on 4.7 vs prior period's 4.6 (same characters cost 1.0–1.35×
   more tokens on 4.7).
10. **Unknown-model warning** — when the prefix doesn't match any known
    Anthropic model, emit `metadata.unknown_model=True` instead of
    silently falling back to Sonnet pricing. Flags Kimi / OpenRouter /
    local-model proxies.
11. **Hostname/machine tag** — `os.uname().nodename` in metadata so the
    UI can pivot by device once multi-machine collection lands.
12. **Extended-thinking share** — distinguish visible output tokens
    from thinking tokens. Claude Code doesn't emit this separately, but
    `stop_reason` correlates.

## Grade Rubric (to reach A / A+)

- **B** (prior): ccusage core math parity.
- **B+** (now): + per-tool-call attribution — YC differentiator.
- **A-**: + 5-hour block analytics + `requestId` dedup.
- **A**: + multi-machine aggregation + conversation replay endpoint.
- **A+**: + LiteLLM pricing sync + subagent attribution + Opus 4.7
  uplift banner + extended-thinking share.
