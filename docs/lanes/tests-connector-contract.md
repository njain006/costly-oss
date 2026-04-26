# Lane: tests-connector-contract

> Make every connector testable without live API access using fixture-driven
> contract tests, property tests, and OpenAPI fuzz.

Branch: `lane/tests-connector-contract`
Owner: Tests/QA lane

## Done (this pass — 2026-04-23)

### Dependencies
- Added to `backend/requirements.txt` (testing section):
  - `respx>=0.21.0` — declarative httpx route mocks
  - `hypothesis>=6.100.0` — property-based testing
  - `pytest-recording>=0.13.0` — vcrpy-backed cassette recording for re-recording fixtures from real APIs

### Contract tests (`backend/tests/contract/`)
One test module per connector, each loads a JSON fixture from
`backend/tests/fixtures/<platform>/` and pins the connector to the vendor's
documented response shape. Includes at least one negative test (auth error /
schema drift / 5xx) per platform.

| Connector | Test file | Fixtures | Tests |
|-----------|-----------|----------|-------|
| Snowflake | `test_snowflake.py` | `usage_in_currency_daily.json`, `metering_daily_history.json` | 3 |
| Anthropic | `test_anthropic.py` | `usage_report_messages.json`, `cost_report.json`, `auth_error.json` | 4 |
| Gemini    | `test_gemini.py` | `billing_export_query.json`, `billing_export_403.json` | 3 |
| dbt Cloud | `test_dbt_cloud.py` | `runs.json`, `auth_error.json` | 4 |
| Fivetran  | `test_fivetran.py` | `groups.json`, `connectors.json`, `usage.json` | 3 |
| Airbyte   | `test_airbyte.py` | `connections.json`, `jobs.json` | 3 |
| Looker    | `test_looker.py` | `login.json`, `query_stats.json`, `users.json`, `pdt_builds.json` | 3 |
| Tableau   | `test_tableau.py` | `signin.json`, `users.json`, `views.json`, `extract_refreshes.json` | 2 |
| Omni      | `test_omni.py` | `users.json`, `queries.json` | 2 |
| Monte Carlo | `test_monte_carlo.py` | `get_user.json`, `tables_monitored.json`, `incidents.json`, `auth_error.json` | 3 |
| GitHub Actions | `test_github.py` | `billing_actions.json`, `user.json` | 4 |
| GitLab CI | `test_gitlab.py` | `user.json`, `projects.json`, `pipelines.json` | 3 |
| Redshift  | `test_redshift.py` | `execute_statement.json`, `describe_statement_finished.json`, `get_statement_result.json`, `access_denied_error.json` | 4 |

**Subtotal: 41 contract tests across 32 JSON fixtures.**

### Property tests
- `tests/contract/test_cost_math_properties.py` — 13 Hypothesis property
  tests across `anthropic`, `openai`, `gemini`, `claude_code` connectors.
  Invariants: non-negativity, monotonicity in any token field, cache-read
  always cheaper than uncached, batch <= on-demand, `total_tokens` never
  overflows for inputs ≤ 10M.

### OpenAPI / Schemathesis
- `tests/contract/test_openapi_spec.py` — 8 tests asserting the FastAPI
  `app.openapi()` dump is valid OpenAPI 3.x and includes every critical
  endpoint with a `responses` block (Schemathesis precondition).
- `tests/contract/dump_openapi.py` — CLI helper that prints `openapi.json`
  to stdout. Used by the CI `connector-contract` job to feed Schemathesis.

### CI
- Added `connector-contract` job to `.github/workflows/ci.yml`. Runs:
  1. The full `tests/contract/` suite.
  2. `pip install schemathesis>=3.30,<4`.
  3. `python -m tests.contract.dump_openapi > openapi.json`.
  4. Background `uvicorn` then `schemathesis run openapi.json --checks all
     --hypothesis-max-examples=5`. Currently non-blocking (`|| true`) — flip
     to gating once the spec is fully clean (see backlog).

### Docs
- `docs/testing/contract-tests.md` — philosophy + layout + how OSS
  contributors should use the suite.
- `docs/connectors/<platform>.md` — appended a "Re-recording contract
  fixtures" section to all 12 connector KB files (dbt-cloud, fivetran,
  airbyte, looker, tableau, omni, monte-carlo, github-actions, gitlab-ci,
  anthropic, gemini, snowflake, redshift).

### Test count delta
- Baseline: 923 passed + 3 skipped = 926 collected.
- After this pass: 977 passed + 3 skipped = 980 collected.
- **+54 net tests** (41 contract + 13 property; the OpenAPI tests run inside
  the same CI job but live alongside the contract tests).

### Backwards compat
- Zero changes to `backend/app/services/connectors/` — the lane only adds
  tests + fixtures + dependencies. Existing 923 tests still green.
- Existing fixture-style tests (`test_anthropic_connector.py`,
  `test_openai_connector.py`, etc.) continue to live in `backend/tests/`
  and run alongside the new `tests/contract/` suite.

## Backlog

### Real-API smoke runs
A nightly GitHub Actions cron job that uses real platform credentials from
GitHub Secrets to:
1. Capture a fresh fixture per connector via `pytest --record-mode=once`.
2. Diff against the checked-in fixture.
3. File an issue (and ping the lane owner) if any vendor's schema changed.

This catches vendor drift the moment it ships, not the moment a customer
hits it. Gated on `CONTRACT_REAL_API=1` env var so it never runs in PRs.

Required GitHub Secrets (one per connector):
- `DBT_CLOUD_API_TOKEN` + `DBT_CLOUD_ACCOUNT_ID`
- `FIVETRAN_API_KEY` + `FIVETRAN_API_SECRET`
- `AIRBYTE_API_TOKEN`
- `LOOKER_CLIENT_ID` + `LOOKER_CLIENT_SECRET` + `LOOKER_INSTANCE_URL`
- `TABLEAU_SERVER_URL` + `TABLEAU_TOKEN_NAME` + `TABLEAU_TOKEN_SECRET`
- `OMNI_API_KEY` + `OMNI_INSTANCE_URL`
- `MC_API_KEY_ID` + `MC_API_TOKEN`
- `GITHUB_CONTRACT_TOKEN` + `GITHUB_ORG`
- `GITLAB_CONTRACT_TOKEN`
- `ANTHROPIC_ADMIN_KEY`
- `GCP_SA_JSON` + `GCP_PROJECT` + `GCP_BILLING_DATASET`
- `SNOWFLAKE_*` (account, user, key)
- `REDSHIFT_AWS_*` (key, secret, region, cluster)

### Mutation testing with mutmut
Add `mutmut` to dev deps and configure it to mutate
`backend/app/services/connectors/*.py`, then verify the contract suite catches
≥ 80% of mutants. This proves the tests actually exercise the cost-math (vs
just exercising the parsing path).

```bash
mutmut run --paths-to-mutate backend/app/services/connectors/
mutmut results
```

### Schemathesis: flip from `|| true` to gating
The current CI step ends with `|| true` so we don't block PRs while the
fuzz pass is shaken out. To gate:
1. Add `--exclude-checks=ignored_auth` for endpoints behind JWT (or rely on
   `--exclude-path-regex` which already skips `/api/(auth|connections|...)/`).
2. Triage any 5xx schemathesis surfaces (likely missing input validation on
   `/api/queries`, `/api/costs` query params).
3. Remove the `|| true`.

### Extend property tests to non-LLM connectors
- `dbt_cloud_connector` — `cost_usd = run_duration / 3600 * 0.50` should be
  monotonic in `run_duration` and bounded by `runs * 24h * $0.50`.
- `fivetran_connector` — the MAR → cost estimator (`mar / 1M × $1`) should
  be monotonic and zero-at-zero.
- `airbyte_connector` — `records / 1M × $15` (Cloud) should be monotonic
  and zero for self-hosted.

### Improve fixture realism
Some fixtures are minimal (e.g. omni queries have only 4 entries). Capture
larger real-account samples and trim/anonymise to ~50 rows so tests cover
pagination, large date ranges, and weekend/holiday gaps.

### Decouple OpenAPI spec test from full app boot
`test_openapi_spec.py::_load_app` imports `app.main.app`, which still
triggers redis/scheduler init at module level. Refactor `app.main` to
defer scheduler binding into a lazy `_init_scheduler()` so the OpenAPI
test can run without `redis` installed.

### `respx` route signatures
`respx.get(url__startswith=...)` is convenient but brittle if multiple
endpoints share a prefix. Tighten the matchers to `url__regex` once we
have more than one endpoint per host.
