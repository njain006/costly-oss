# Lanes — Parallel-Development Dashboard

Costly uses a multi-lane, multi-worktree development model. Each lane runs in its own git worktree on its own branch (`lane/<name>`), owned by a Claude agent, and commits are rebased / merged into `main` via PRs. This directory is the index — each lane maintains its own file here with current state, last commit SHA, and what's next.

## Active Lanes

| Lane | Branch | Focus | Doc |
|------|--------|-------|-----|
| DOCS | `lane/docs` | Documentation: connectors KB, deployment, architecture, changelog, docs site. | [`docs.md`](./docs.md) |
| CONNECTORS | `lane/connectors` | Per-connector code: data sources, SKU taxonomy, tests. | `connectors.md` _(owned by connectors lane)_ |
| UI | `lane/ui` | Frontend: dashboards, AI-costs view, demo page, setup page. | `ui.md` _(owned by ui lane)_ |
| AGENT | `lane/agent` | AI agent: tools, expert agents, knowledge bases, chat UX. | `agent.md` _(owned by agent lane)_ |
| INFRA | `lane/infra` | Docker, nginx, scheduler, deploy, observability. | `infra.md` _(owned by infra lane)_ |

> Lanes that do not own their file yet simply don't have one checked in. The DOCS lane aggregates this index but does NOT edit other lanes' files — each lane co-edits its own page on its own branch.

## How this works

1. Each lane commits on its `lane/<name>` branch inside its own worktree. Worktrees live under `.claude/worktrees/`.
2. When a lane finishes a unit of work, it updates its `docs/lanes/<name>.md` with:
   - **Done** (what just shipped, with commit SHAs)
   - **In progress** (what's being worked on right now)
   - **Backlog** (what's queued next)
3. A lane may never edit another lane's `docs/lanes/*.md` file. The DOCS lane owns the index (this file) and its own page.
4. When all lanes rebase onto `main`, the index renders a full cross-lane status.

## Merging conventions

- Each lane opens a PR from `lane/<name>` → `main`.
- Do not merge across lanes; each lane merges its own PR.
- If a lane touches a file owned by another lane (e.g. the DOCS lane editing a router), either (a) handshake with the owning lane first, or (b) leave a `TODO(docs-lane)` marker for the owning lane to address.

## Lane scope boundaries (short version)

| Lane | May edit | Must NOT edit |
|------|----------|---------------|
| DOCS | `docs/**`, `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `frontend-next/src/app/docs/**` (docs site only) | Any other code |
| CONNECTORS | `backend/app/services/connectors/**`, related tests, `docs/connectors/*.md` change logs | Routers, UI, scheduler |
| UI | `frontend-next/src/**` | Backend code |
| AGENT | `backend/app/services/agent.py`, `services/expert_agents.py`, `backend/app/knowledge/**`, `routers/chat.py` | Connectors, UI |
| INFRA | `docker-compose*.yml`, `nginx/**`, `backend/Dockerfile*`, `frontend-next/Dockerfile`, scheduler hooks | Business logic |

## Current repo baseline

- Head commit as of this doc: `988728f` — revert: restore frontend port 3000:3000 (canonical).
- Last docs-lane commit: _pending — this is the first commit on `lane/docs`._
