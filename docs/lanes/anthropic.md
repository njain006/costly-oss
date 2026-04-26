# Anthropic Connector — Lane Backlog

Tracks open work for `lane/anthropic`. Authoritative code:
`backend/app/services/connectors/anthropic_connector.py`.
Knowledge base: `/docs/connectors/anthropic.md` (read first).

## Status: A-

Connector hits the real Admin API (`/usage_report/messages` + `/cost_report`),
resolves list pricing with longest-prefix match, applies cache + service-tier
multipliers, isolates priority / priority_on_demand / batch / flex into
separate UnifiedCost records, surfaces deprecation notices, promotes
`inference_geo` to `UnifiedCost.project`, and emits per-workspace daily
rollup records that feed `/api/anomalies` without any Anthropic-specific
code in the detector.

## Shipped (2026-04-24)

- Per-workspace daily rollup records (`resource="workspace:<id>"`,
  `metadata.type="rollup"`) — flow into `anomaly_detector`'s per-resource
  z-score path so workspace-level spikes light up on `/api/anomalies`
  with zero anomaly-engine changes.
- Per-api_key rollups (opt-in via `emit_api_key_rollups=True`).
- Priority tier expansion: `priority` (1.25×), `priority_on_demand` (1.5×),
  `flex` (0.5×) now isolated into separate records tagged
  `metadata.isolated_tier=true`.
- `DEPRECATED_MODELS` registry + `metadata.deprecation_notice` on every
  primary record emitting deprecated-model usage; rollups accumulate
  `deprecated_cost_usd` so the dashboard can quantify migration debt.
- `inference_geo` promoted to `UnifiedCost.project` (first-class grouping
  for data-residency).
- `/api/ai-costs` extended (read-only) with `workspace_breakdown`,
  `tier_breakdown`, `kpis.deprecated_spend_usd`; rollups excluded from
  primary aggregates via `metadata.type != "rollup"`.
- 42 new parametrized tests covering workspace × service_tier × geo combos,
  deprecation, rollup emission, tier isolation.

## Backlog

### Priority 1 — OpenTelemetry ingestion (next)
- Accept `otel` credential shape that points at a local OTLP collector
  dumping Anthropic SDK spans.
- Parse `gen_ai.usage.*` attributes (input/output/cache tokens, model).
- Emit UnifiedCost records in the same shape as the Admin API path so
  sidecar-wrapped traffic becomes visible alongside Admin API rollups.
- Blocked on: confirming the Anthropic SDK actually emits per-call spans
  with usage (check `anthropic` Python >= 0.50).

### Priority 2 — Nightly LiteLLM pricing sync
- Task: fetch `model_prices_and_context_window.json` from
  github.com/BerriAI/litellm nightly and merge into `MODEL_PRICING`.
- Fallback to committed table if fetch fails.
- Hash-based cache so we only rebuild when the upstream changes.

### Priority 3 — Opus 4.7 tokenizer uplift banner
- When Opus 4.7 share of tokens exceeds a threshold AND the previous
  period had significant Opus 4.6 usage, surface a "watch for tokenizer
  uplift" recommendation.
- Needs: 4.6 → 4.7 per-workspace migration detection.

### Priority 4 — Batch savings recommendation
- When a workspace has significant `standard` spend on a model that also
  has `batch` traffic (proving the workload supports async), recommend
  "switch X% of standard to batch → $Y/mo saved".
- Needs: latency-sensitivity inference (rough heuristic: if `priority`
  traffic is low, batch-eligibility is high).

### Priority 5 — Vertex/Bedrock reconciliation
- AWS CUR has `Amazon Bedrock` line items for Anthropic models; BigQuery
  billing has `Vertex AI` items for the same.
- Claim those $s for the Anthropic totals AND keep them on the cloud
  connector totals (avoid double-counting via an `owner_connector` tag).

### Priority 6 — Managed Agents cost breakdown
- 2025-launched product with its own priority premium. Surface as a
  separate `service` value so tier analytics can isolate it.

### Priority 7 — Invoice reconciliation
- Monthly: compare Admin API cost_report sum vs Stripe invoice.
- Surface deltas > 2% as anomalies tagged `type=invoice_drift`.

## Debugging Notes

- `emit_workspace_rollups` defaults to True. Setting False in credentials
  is appropriate for single-workspace orgs where the rollup is redundant.
- Rollups never double-count in `/api/ai-costs` because of the
  `metadata.type != "rollup"` filter on `base_match`.
- Anomaly detector treats `workspace:<id>` as a distinct resource and
  runs z-score on its daily series — same threshold (2.0) as model-level.
- `isolated_tier=True` on a UnifiedCost is the right flag for the budget
  tracker to gate tier-specific budgets off of.

## Test Coverage

185 tests green on:
```
backend/tests/test_anthropic_connector.py
backend/tests/test_connectors.py
```

New test classes (all added 2026-04-24):
- `TestServiceTierIsolation` — 5 cases (priority_on_demand, flex,
  ISOLATED_SERVICE_TIERS membership, mixed-tier day)
- `TestDeprecationSurfacing` — 5 cases (parametrized over 8 deprecated
  model IDs, longest-prefix win, notice injection)
- `TestWorkspaceRollups` — 7 cases (emission toggle, aggregation, tier
  mix, api_key opt-in, missing workspace)
- `TestInferenceGeoAsProject` — 3 cases (populate, empty, rollup aggregate)
- `TestParametrizedDimensions` — 8 parametrized combos (workspace × tier × geo)
