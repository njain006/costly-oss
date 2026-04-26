# Lane: DOCS

> Keep every docs surface current and discoverable. Maintenance + gap-filling, not research.

Branch: `lane/docs`
Worktree: `.claude/worktrees/agent-a866ebd6531f3f8c8`

## Scope

- `docs/**`
- `README.md`
- `CONTRIBUTING.md`
- `CHANGELOG.md`
- `frontend-next/src/app/docs/**` (only if the docs lane ships a real `/docs` site)

Must NOT edit: backend code, connectors, routers, UI components outside `src/app/docs/`, Docker / nginx.

## Done

### Session 2026-04-23

- Created `CHANGELOG.md` seeded from `git log` since 2026-04-23 — marketing reposition, Claude Code connector, 6 connector overhauls (Anthropic, OpenAI, Gemini, Snowflake, Databricks, BigQuery), multi-platform setup page, demo revamp, AI Costs view.
- Created `docs/deployment.md` — self-host recipe, `docker-compose.override.yml` pattern (including the `~/.claude` mount for Claude Code connector), secret generation recipes, per-platform first-sync expectations, production hardening checklist.
- Created `docs/architecture.md` — current mermaid + ascii diagrams, module-by-module responsibilities, request lifecycle (dashboard read + AI agent + scheduled jobs), MongoDB data model, auth model, caching strategy, extension checklists.
- Refreshed `README.md` — AI-first tagline, added Claude Code connector to Supported Platforms table, linked to `/setup`, added a Documentation table of contents pointing at new docs, moved connector-registration instructions into the new `connectors/` subdirectory path.
- Created `docs/lanes/README.md` — index of all lanes with scope boundaries and handshake rules.
- Created this file.

## In progress

_Nothing in-flight at session end. The commit to `lane/docs` is pending branch creation (current worktree is on `worktree-agent-a866ebd6531f3f8c8`; branch switch was denied by sandbox and must be done manually before committing)._

## Backlog (prioritised)

### High value, small

1. **Per-connector change log sync** — Walk each `docs/connectors/*.md` file and append a `Change Log` entry matching the code changes since 2026-04-23. Six connectors need real entries (Anthropic, OpenAI, Gemini, Snowflake, Databricks, BigQuery); the other eleven should carry a "2026-04-24: Initial KB — no code change this cycle" marker if only the KB was touched. The existing entries all say only "Initial knowledge-base created by overnight research run."
2. **`CONTRIBUTING.md` sweep** — verify the Adding a Connector steps match the new `services/connectors/` directory layout (was `services/<platform>_connector.py`, now `services/connectors/<platform>_connector.py`).
3. **`backend/.env.example`** — the env example still lacks `APP_URL` and `LLM_MODEL` as sample values. Check that every variable referenced in `docs/deployment.md` exists in the example.
4. **`docs/agent-chat-ux.md` + `docs/dashboard-visualization-spec.md` TOC entries** — the Documentation section in `README.md` already links to them, but they may need a one-line summary header so the link target lands on something meaningful.

### Larger (session-sized)

5. **Ship a real `/docs` site** — currently `/docs` 404s after the nav label swap to "Setup". Build `frontend-next/src/app/docs/page.tsx` as the index, surface `docs/connectors/*.md` via `fs.readFile` + remark rendering at `docs/connectors/[slug]/page.tsx`. Use the existing Tailwind + shadcn patterns (no new dep beyond `remark` / `react-markdown` if possible).
6. **Screenshots in `README.md`** — add one hero screenshot and one AI-agent-in-action screenshot. Would dramatically improve GitHub-stars conversion on a cold landing.
7. **Claude Code connector quick-start demo GIF or mp4** — this connector is the most viral differentiator; it deserves a 20-second screen recording showing "point it at your ~/.claude directory, see per-project cost" embedded in `docs/connectors/claude-code.md` and the README.
8. **`docs/roadmap.md`** — a simpler-to-skim sibling of `connector-roadmap-2026.md` that cross-references the agent / UI / infra lanes, not just connectors.
9. **`docs/security.md`** — how credentials are encrypted (Fernet, `ENCRYPTION_KEY` lifecycle), what a read-only Snowflake role looks like, how CUR 2.0 S3 permissions should be scoped, etc. Especially important for enterprise sales.

### Deferred

10. **Auto-generated API reference** — FastAPI already emits OpenAPI at `/api/openapi.json`. Wire up `redoc` / `scalar` on `/docs/api` once the docs site lands.
11. **Per-page screenshots in the dashboard-visualization-spec** — a lot of value for new contributors but blocked on the UI lane stabilising the pages.

## Conventions

- No "Co-Authored-By: Claude" in commits (maintainer preference).
- Commit type for doc-only changes: `docs:`.
- Commit messages focus on _why_ (e.g. `docs: seed CHANGELOG so releases aren't reverse-engineered from git log`) rather than _what_.
- Never proactively create markdown documentation the user didn't ask for — but the ask for this lane is explicit, so this doc is part of the ask.

## Handshakes needed

- **INFRA lane** — if they change `docker-compose.yml` ports or volumes, `docs/deployment.md` needs an update. Leave a `TODO(docs-lane)` marker.
- **CONNECTORS lane** — when a connector ships, append to both `CHANGELOG.md` and `docs/connectors/<platform>.md` change log. If the connectors lane prefers to own that write, docs lane can verify instead of authoring.
- **UI lane** — if they ship a real `/docs` site first, coordinate on the component patterns before the docs lane starts wiring markdown rendering.
