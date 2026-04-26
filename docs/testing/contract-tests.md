# Connector Contract Tests

> Pin every connector to a vendor's documented API shape using JSON fixtures —
> no live network access required for the suite to pass, and a one-line
> command to re-record when vendors change their schema.

## Why fixtures, not mocks?

The original connector tests used `unittest.mock.patch` directly on `httpx`
or boto3 calls inside the test body. That works, but it means:

1. **The vendor API shape is encoded in test code, not data.** Changes are
   buried inside `MagicMock(...)` calls scattered across hundreds of lines.
2. **There's no single source of truth.** When a vendor's response changes,
   you're hunting through Python files instead of looking at one JSON fixture.
3. **OSS contributors can't easily verify their connector against the real
   thing.** They have no way to capture a fresh response and replay it.

Contract tests fix all three:

- **Fixtures live in `backend/tests/fixtures/<platform>/`.** They are exactly
  what the vendor returns — checked into git so anyone can read the schema.
- **Tests live in `backend/tests/contract/test_<platform>.py`.** Each test
  loads a fixture, mocks the HTTP layer with `respx` (or boto3 for AWS APIs),
  and asserts the connector produces the expected `UnifiedCost` records.
- **Re-recording is one command per platform.** When a vendor changes their
  schema, the maintainer points the test at a real account once and commits
  the new fixture.

## Layout

```
backend/
├── tests/
│   ├── contract/                 # one test_<platform>.py per connector
│   │   ├── conftest.py           # fixture loader
│   │   ├── test_anthropic.py
│   │   ├── test_dbt_cloud.py
│   │   ├── test_fivetran.py
│   │   ├── ... (12 connectors)
│   │   ├── test_cost_math_properties.py    # Hypothesis property tests
│   │   ├── test_openapi_spec.py            # OpenAPI dump validity
│   │   └── dump_openapi.py                 # CLI: print openapi.json to stdout
│   └── fixtures/
│       ├── anthropic/
│       │   ├── usage_report_messages.json
│       │   ├── cost_report.json
│       │   └── auth_error.json
│       ├── dbt_cloud/
│       │   ├── runs.json
│       │   └── auth_error.json
│       └── ... (one dir per platform)
```

## Three layers of tests

| Layer | What it verifies | Tools |
|-------|------------------|-------|
| Contract (`test_<platform>.py`) | Connector parses vendor response → `UnifiedCost` correctly | `respx` (httpx mock), `unittest.mock` for boto3 |
| Property (`test_cost_math_properties.py`) | Cost-math invariants hold for any reasonable token input | `hypothesis` |
| OpenAPI (`test_openapi_spec.py` + CI Schemathesis) | Every FastAPI endpoint conforms to its declared schema | `fastapi.openapi`, `schemathesis` |

### Contract layer

Each `test_<platform>.py` file pins one connector to one or more endpoints.
Pattern:

```python
import respx, httpx
from app.services.connectors.dbt_cloud_connector import DbtCloudConnector
from tests.contract.conftest import load_fixture

@respx.mock
def test_fetch_costs_parses_runs_into_unified_costs():
    respx.get("https://cloud.getdbt.com/api/v2/accounts/12345/runs/").mock(
        return_value=httpx.Response(200, json=load_fixture("dbt_cloud", "runs"))
    )
    costs = DbtCloudConnector(creds).fetch_costs(days=7)
    assert all(c.platform == "dbt_cloud" for c in costs)
```

Every test file should include at least one **negative** test (auth error,
rate limit, schema drift) so we catch error-path regressions too.

### Property layer

`tests/contract/test_cost_math_properties.py` uses Hypothesis to feed
randomly-generated `TokenUsage` values into `estimate_cost` and assert
invariants like:

- `cost >= 0` for any non-negative inputs
- `cost` is monotonic-non-decreasing in any single token field
- cache-read tokens are strictly cheaper than uncached input tokens
- batch pricing is `<=` on-demand pricing

Hypothesis shrinks failures down to the minimal counter-example, which
catches off-by-one and rounding bugs that fixed-fixture tests miss.

### OpenAPI layer

`tests/contract/test_openapi_spec.py` checks that the FastAPI app's
`openapi()` dump is valid OpenAPI 3.x and includes all critical routes.

In CI (the `connector-contract` job in `.github/workflows/ci.yml`), we then
run [`schemathesis`](https://schemathesis.readthedocs.io) against a live
backend to fuzz every endpoint and assert no 500s and no schema mismatches.

## Re-recording fixtures

When a vendor changes their API, the maintainer regenerates the fixture
once against a real account and commits the result.

The general pattern (per platform) is in each connector's KB file under
`docs/connectors/<platform>.md → "Re-recording contract fixtures"`. The
short version:

```bash
cd backend
# Set the platform's credentials, then:
<PLATFORM>_API_KEY=xxx pytest tests/contract/test_<platform>.py --record-mode=once
```

Then **sanitize the captured JSON** before committing — strip account IDs,
emails, tokens, internal hostnames, anything an external contributor
shouldn't see.

If the vendor's response has changed shape (added/renamed/removed fields),
update the connector code AND the contract test in the same PR. The
fixture is the source of truth; if you have to special-case anything inside
the test body to make it pass, that's a smell — push the change into the
fixture instead.

## Comparison with alternatives

We considered (and rejected) several alternatives:

- **VCR / pytest-recording** for everything: works for HTTP but doesn't help
  with boto3 (Snowflake DBAPI cursors) or BigQuery's gRPC under the hood.
  We use `pytest-recording` only as the optional re-record path; the actual
  test runs against checked-in JSON to keep the suite hermetic.
- **A single mega-fixture per connector**: makes drift hard to spot. One
  fixture per endpoint keeps diffs reviewable.
- **Generated fixtures from OpenAPI schemas**: most vendors don't publish
  faithful OpenAPI specs (Snowflake, BigQuery, Anthropic Admin API are all
  un-OAS). Hand-curated fixtures are the only honest source of truth.

## How OSS contributors should use this

1. Find the connector you want to improve (e.g. `fivetran_connector.py`).
2. Open `backend/tests/contract/test_fivetran.py` and the fixture it loads
   from `backend/tests/fixtures/fivetran/`.
3. Make your code change + update the fixture if the API shape is now
   different. Add a new test if you're adding a new code path.
4. Run `cd backend && pytest tests/contract/test_fivetran.py -v` locally —
   no Fivetran credentials needed.
5. Open a PR. CI runs the same suite against the same fixtures; reviewers
   can see the diff inline.

## Related

- `backend/tests/conftest.py` — shared pytest fixtures (credentials, mock_db).
- `backend/tests/contract/conftest.py` — `load_fixture` helper.
- `.github/workflows/ci.yml` — `connector-contract` job runs all of this in CI.
- `docs/lanes/tests-connector-contract.md` — lane log + backlog.
