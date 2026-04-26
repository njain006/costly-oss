# Lane: TESTS-CI-COVERAGE

> Make CI a real safety net — every push runs the full quality gate, results are visible in the README, broken `main` is rare.

**Branch:** `lane/tests-ci`
**Worktree:** `.claude/worktrees/agent-aac8cc7b37fcb9f2f`

**Green bar (local):**
- `cd backend && pytest tests/ -x -q --ignore=tests/test_api.py`
- `cd frontend-next && npx next build`

## Scope

May edit:
- `.github/workflows/**`
- `pyproject.toml`
- `frontend-next/package.json` (scripts only — no new dependencies)
- `README.md` (badges section only)
- `docs/lanes/tests-ci.md` (this file)

Must NOT edit: any source code, any test code, anything outside the list above.

## Done (this session)

### Refactored `.github/workflows/ci.yml` into parallel jobs
Split the monolithic workflow into independent fast-feedback jobs:
- `backend / lint` — ruff check + ruff format check + mypy (advisory while baselines clean up; `continue-on-error: true`).
- `backend / tests` — pytest with `--cov=app --cov-report=xml`; uploads HTML coverage artifact + pushes XML to Codecov via `codecov/codecov-action@v4`.
- `frontend / lint` — eslint + `tsc --noEmit` (advisory).
- `frontend / build` — `next build`.
- `e2e / playwright` — gated on `backend-tests` + `frontend-build` (preserved from original workflow).
- `security / no-secrets` — preserved.
- `ci / summary` — single rollup job that hard-fails on any required job (tests/build/e2e/secrets) and reports lint as advisory. Use this as the **single required check** for branch protection on `main`.

### Concurrency control
- `concurrency.group = ci-${{ github.workflow }}-${{ github.ref }}`
- `cancel-in-progress = ${{ github.ref != 'refs/heads/main' }}` — superseded PR runs are cancelled, but a release on `main` is never killed mid-flight.
- Same pattern applied to `security.yml` and `release.yml`.

### Reusable workflows
- `.github/workflows/_setup-python.yml` — callable Python+pip setup (`workflow_call`), with optional `install-extras` for `lint` / `audit` tool installs.
- `.github/workflows/_setup-node.yml` — callable Node setup. Documented limitation: each `workflow_call` runs in its own runner so node_modules doesn't cross jobs; this is the canonical reference for Node version + cache key, not a state-passing mechanism. (Per [GitHub docs on reusable workflows](https://docs.github.com/en/actions/using-workflows/reusing-workflows).)

### Coverage → Codecov
- pytest invoked with `--cov=app --cov-report=term-missing --cov-report=xml:coverage.xml --cov-report=html`.
- HTML uploaded as artifact (`backend-coverage-html`).
- XML pushed to Codecov; `CODECOV_TOKEN` is optional (token-less works for public repos, picked up if set).
- README now shows a `codecov` badge that will start populating after the first successful push to `main`.

### Dependency + filesystem security scanning (`.github/workflows/security.yml`)
- `audit / pip` — `pip-audit` against `backend/requirements.txt`. Filters to HIGH/CRITICAL via inline Python; everything else is reported in the JSON artifact but doesn't block.
- `audit / npm` — `npm audit --omit=dev --audit-level=high` (production deps only — devDep CVEs in test runners are noisy).
- `audit / trivy` — `aquasecurity/trivy-action` filesystem scan, SARIF uploaded to the Security tab via `github/codeql-action/upload-sarif`. Severity filter HIGH/CRITICAL, `ignore-unfixed: true`.
- Opt-out: PR label `skip-audit` skips both `pip-audit` and `npm audit` (Trivy still runs — repo-wide signal). Removing the label and re-running CI re-enables the gate.
- Weekly cron `0 9 * * 1` so a vendor advisory disclosed mid-week doesn't go unnoticed for two weeks.

### Lint config (`pyproject.toml`)
- New file at repo root. Tooling-only — no `[project]` section because the package isn't published.
- Configures ruff (lint + format), black (kept for editor interop, ruff is canonical), mypy (with `pydantic.mypy` plugin), pytest, and coverage in one place.
- ruff rule set is conservative: `E,F,W,I,B,UP,C4,SIM,PL,RUF` with PLR0913/PLR0911/PLR0912/PLR0915/PLR2004 suppressed (FastAPI handlers + tests routinely trip these).
- mypy currently runs with `ignore_missing_imports = true` and `no_strict_optional = true` so the first PR isn't a 1000-error wall. Tighten incrementally.

### Frontend `package.json` script additions (no deps)
- `lint:fix` → `eslint --fix`
- `typecheck` → `tsc --noEmit`
- `test:e2e` → `playwright test`

(Prettier was considered for `format` / `format:check` but deferred — would require a new dep, which the lane scope forbids.)

### Release automation (`.github/workflows/release.yml`)
- `googleapis/release-please-action@v4` configured but only triggers on push to `main`. On the first qualifying push it opens a release PR with version bump + CHANGELOG.md updates. Picked release-please over auto-changelog (generator only, no PR/tag automation) and over semantic-release (requires npm token + plugin sprawl).
- Strategy `simple`, `changelog-path: CHANGELOG.md` so it appends to the file the docs lane already maintains.
- `skip-github-release: true` — the release PR is the audit trail; maintainers publish marketing releases manually.

### README badges
- CI status, Security status, Codecov %, MIT license, Latest release (semver-sorted), GitHub stars, Live demo. All shields.io / vendor-native badges, no custom hosting.

## In progress

_Nothing in-flight at session end._

> **Heads-up:** the worktree is on branch `worktree-agent-aac8cc7b37fcb9f2f`, not `lane/tests-ci`. Branch creation (`git switch -c lane/tests-ci`) was blocked by sandbox permissions in this run. Rename before opening the PR:
>
> ```bash
> git branch -m worktree-agent-aac8cc7b37fcb9f2f lane/tests-ci
> ```

## Backlog (prioritised)

### High value, small
1. **Branch protection on `main`** — flip on via the GitHub UI (Settings → Branches → Add rule):
   - Require status check `ci / summary` to pass.
   - Require linear history.
   - Require PR review (1 reviewer minimum).
   - Block force pushes.
   This isn't enabled by API in this lane — it's a one-time UI/REST call by a repo admin. Once `ci-summary` is green on a few PRs, it's safe to require.
2. **`.pre-commit-config.yaml`** — out of scope for this lane (would touch a new repo-root file). Add ruff + black + commitlint hooks. Document install in README:
   ```bash
   pip install pre-commit && pre-commit install
   ```
3. **`.github/dependabot.yml`** — out of scope here (different file path). Add weekly bumps for `pip` (in `/backend`) and `npm` (in `/frontend-next`) and `github-actions` (in `/`). Renovate evaluated and rejected: Dependabot is zero-config and first-party; Renovate's grouping is nicer but not worth the extra config surface yet.
4. **Codecov configuration file** (`.codecov.yml`) — set project coverage target (start at the current measured %, ratchet up). Out of scope here.
5. **Drop the `continue-on-error: true` flags on lint jobs** once ruff/mypy/eslint baselines are clean. Tracked: 1 commit per tool.
6. **Frontend coverage** — Vitest lane will land per-component coverage; once it does, add a second Codecov upload with `flags: frontend` so the project % is split per component.

### Larger (session-sized)
7. **Lighthouse CI** — add a workflow that runs `lhci autorun` against `npm start` for accessibility, perf, SEO, best-practices on every PR. Budget file lives in `frontend-next/lighthouserc.json`. Skip when the only changed paths are `backend/**` or `docs/**`.
8. **semantic-release** — only if release-please proves too rigid for the eventual monorepo split (separate backend wheel + frontend npm package).
9. **Renovate** if dependabot's grouping pain becomes acute.
10. **OIDC for cloud deploy** — GitHub → AWS OIDC trust + a deploy job in a separate `deploy.yml` so we stop relying on long-lived AWS access keys. Blocked on infra-lane choosing the deploy target (current EC2 vs ECR/Fargate vs Fly).
11. **Test sharding** — once `backend/tests/` exceeds ~5 min wall time, switch to `pytest -n auto` (pytest-xdist) and shard via matrix.

### Deferred
12. **Mutation testing** (`mutmut`) — only meaningful once line coverage is ≥85%.
13. **Performance regression tests** — k6 / locust on the API endpoints, baseline + diff. Not worth wiring until a paying customer is on the platform.

## Conventions

- No `Co-Authored-By: Claude` trailers (maintainer preference, repo-wide).
- Commit type for CI / tooling changes: `ci:` (workflows), `chore:` (config files like `pyproject.toml`), `docs:` (this file + README).
- Every commit MUST keep the local green bar green:
  - `cd backend && pytest tests/ -x -q --ignore=tests/test_api.py`
  - `cd frontend-next && npx next build`
- Every workflow change MUST be lintable as YAML before commit. Use `actionlint` or push to a fork PR if uncertain.
- Lint jobs default to `continue-on-error: true` until each tool's baseline is clean (no surprise red bars on first contributor PR).

## Handshakes needed

- **DOCS lane** — README badges section is now expanded; if docs lane adds a hero screenshot they should drop it below the badges, not above.
- **INFRA lane** — Trivy will flag CVEs in any new base image they pin in `Dockerfile*`. Coordinate before pinning a new base.
- **AGENT / CONNECTORS lanes** — once they ship `pip` deps, those flow through `pip-audit` automatically. No handshake needed unless they want to opt a PR out via `skip-audit`.

## Required CI checks (for branch protection on `main`)

When a maintainer enables branch protection, this is the minimum required set:

| Check | Required | Rationale |
|-------|----------|-----------|
| `ci / summary` | YES | Single rollup — fails if any of tests/build/e2e/secrets failed. |
| `audit / pip` | RECOMMENDED | Catches HIGH/CRITICAL CVEs in backend deps. |
| `audit / npm` | RECOMMENDED | Catches HIGH/CRITICAL CVEs in frontend deps. |
| `audit / trivy` | OPTIONAL | Reports to Security tab — useful as signal, noisy as gate. |
| `release-please` | NO | Only runs on `main`; not a PR check. |
| Individual `backend / *` / `frontend / *` jobs | NO | Already covered by `ci / summary`. |
