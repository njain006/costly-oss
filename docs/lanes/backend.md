# Backend Lane — Shared Plumbing

This lane owns cross-cutting backend infrastructure that every connector + router depends on. Per-connector files (`backend/app/services/connectors/<vendor>_connector.py`) are OUT of scope — they have their own lanes.

**Branch:** `lane/backend`

**Green bar:** `cd backend && pytest tests/ -x -q --ignore=tests/test_api.py` (currently 700 passed, 2 skipped)

---

## Done

### Unified Error Taxonomy (2026-04-23)
- **Files:** `backend/app/services/connectors/errors.py`, `backend/tests/test_connector_errors.py`
- **Coverage:** 100% (48 tests)
- `CostlyConnectorError` base + 9 concrete subclasses (`InvalidCredentialsError`, `ScopeMissingError`, `WarehouseNotFoundError`, `APIDisabledError`, `RateLimitedError`, `QuotaExceededError`, `VendorDownError`, `SchemaDriftError`, `DataLaggedError`).
- Each has stable `code`, `http_status`, typed extras (e.g. `RateLimitedError.retry_after`, `ScopeMissingError.required_scope`, `WarehouseNotFoundError.resource_name`, `SchemaDriftError.missing_field`, `QuotaExceededError.reset_at`), and a computed `remediation_url` (`https://docs.costly.dev/errors/<code>`).
- `register_connector_exception_handler(app)` — FastAPI handler that converts any `CostlyConnectorError` into a `{"error": {...}}` JSON envelope with the right HTTP status and a `Retry-After` header for rate-limited responses. **Already wired into `app/main.py`.**
- `is_retryable(exc)` — single source of truth for "is this transient?" (retry decorator consumes it).

### Shared Retry Decorator (2026-04-23)
- **Files:** `backend/app/services/connectors/retry.py`, `backend/tests/test_connector_retry.py`
- **Coverage:** 100% (39 tests)
- `@with_retry(max_attempts=5, backoff_base=1.0, backoff_cap=60.0, jitter=True)` — works on BOTH sync and async functions. Auto-dispatches via `inspect.iscoroutinefunction`.
- Exponential backoff with jitter: `min(cap, base * 2**(attempt-1)) + random(0, base)`.
- Retries on taxonomy's transient set (`RateLimitedError`, `DataLaggedError`, `VendorDownError`) + `httpx.RequestError`. Never retries on the permanent set — caller can't override that invariant.
- Honors vendor `Retry-After` header — uses `RateLimitedError.retry_after` as the minimum sleep for that attempt (still capped by `backoff_cap`).
- On exhaustion, re-raises wrapped in `VendorDownError` preserving `platform` / `endpoint` context.
- `raise_for_status_with_taxonomy(response, platform, endpoint)` — maps any `httpx.Response` onto the taxonomy (`401 → InvalidCredentialsError`, `403 → ScopeMissingError`, `404 → WarehouseNotFoundError`, `409 → APIDisabledError`, `429 → RateLimitedError` with `Retry-After` parsed, `5xx → VendorDownError`). Parses non-integer `Retry-After` headers (HTTP-date form) gracefully.
- `compute_backoff()` / `sleepers` are exposed for deterministic testing.
- `docs/connector-ground-truth.md` "Cross-cutting standards" section updated to reflect what shipped.

---

## In Progress

_(nothing active)_

---

## Backlog

Picked from `docs/connector-ground-truth.md`, ordered by highest cross-lane unlock:

1. **FOCUS 1.2 normalization service** — `backend/app/services/focus.py` with `focus_row_from_unified(cost: UnifiedCost) -> dict`. Maps every `UnifiedCost` field onto FOCUS 1.2 columns (see ground-truth doc §"FOCUS 1.2 Schema Normalization Target"). Unlocks external BI tool ingestion.
2. **Consolidated anomaly detection service** — the current `services/anomaly_detector.py` has drifted; various routers also inline anomaly logic (`routers/anomalies.py`). Fold into one service with Z-score + DoD + WoW analysis and a single `Anomaly` pydantic model. Target: `backend/app/services/anomalies.py`.
3. **MCP server** — `backend/app/services/mcp_server.py` exposing `get_claude_spend`, `get_platform_spend`, `get_cache_efficiency`, `explain_cost_spike`, `get_budget_status` over MCP (stdio + Streamable HTTP). YC W26 distribution lever.
4. **Shared `TokenUsage` dataclass** — already defined in `claude_code_connector.py`. Extract to `backend/app/services/connectors/tokens.py` so other AI connectors (Anthropic, OpenAI, Gemini) import a single frozen dataclass instead of redefining their own.
5. **`pricing_overrides` resolver** — one function that every connector calls to resolve a (service, sku) → unit price, respecting the precedence chain in ground-truth §"Honoring `pricing_overrides`". Removes duplicated override lookup logic.
6. **Structured logger** — `backend/app/services/telemetry.py` with a JSON log formatter + correlation IDs. Today each service uses ad-hoc `print()` / plain `logging`. Small lift, big ops payoff.

---

## Scope Guardrails (for future agents working this lane)

- **YES:** new files in `backend/app/services/` (including `services/connectors/` IF it's a shared module like `retry.py` / `errors.py` / `tokens.py`), `backend/app/models/`, `backend/app/utils/`.
- **YES:** cross-cutting edits in `backend/app/main.py`, `backend/app/routers/` (e.g. wiring a new exception handler, not per-route work).
- **NO:** edits to individual connector files (`backend/app/services/connectors/<vendor>_connector.py`) — those have their own lanes.
- **NO:** deploy / push / infra changes.
- **NO:** `Co-Authored-By: Claude` trailers.
