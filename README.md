# Book Recommendation Service (BFF)

Pass-through backend in front of the [book-recommendation agent](../book-recommendation-agent)
(LangGraph). It authenticates the caller, derives identity and injects it into the agent run
context, streams responses back to the frontend, drives the HITL confirmation flow, and exposes
usage / profile HTTP endpoints. Built with **uv + FastAPI**; shares the agent's Postgres and DB
tooling.

See [TODO.md](./TODO.md) for the feature backlog and [CLAUDE.md](./CLAUDE.md) for project rules.

## Quickstart

```bash
uv sync                          # install deps + create the venv
cp .env.example .env             # (a dev .env is already provided for local sqlite)
make run                         # http://localhost:8000/docs
```

Verify identity wiring: `curl -s localhost:8000/me` (works because `DEV_AUTH=1`).

## Verification

The Makefile is the single source of truth (CI and pre-commit only call it).

```bash
make check   # lint (ruff + mypy + codespell) + tests — fast, offline
make ci      # what GitHub Actions runs verbatim: lint + coverage
make format  # auto-fix formatting + import order
```

## Layout

```
src/service/
  main.py        FastAPI app (health, /me, feature routers to come)
  config.py      settings from env / .env
  auth.py        pluggable identity resolver (dev stub → real JWT)
  db/            engine/session/Base (same tooling as the agent; shared Postgres)
scripts/         create_tables.py (dev DB setup)
tests/           unit tests
```
