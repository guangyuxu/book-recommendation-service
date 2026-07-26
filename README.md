# Book Recommendation Service (BFF)

Pass-through backend in front of the [book-recommendation agent](../book-recommendation-agent)
(LangGraph). It **verifies** the caller's access token (RS256, using the
[accounts service](../book-recommendation-accounts)'s public key), derives identity and injects it
into the agent run context, streams responses back to the frontend, and drives the HITL
confirmation flow. Built with **uv + FastAPI**.

The BFF holds **no database connection and no private key**: token issuance (signup/login) and
family/child CRUD live in the accounts service. The BFF only verifies tokens and proxies chat.

See [ACCOUNTS_SPLIT_PLAN.md](./ACCOUNTS_SPLIT_PLAN.md) for the split architecture and
[CLAUDE.md](./CLAUDE.md) for project rules.

## Quickstart

```bash
uv sync                          # install deps + create the venv
cp .env.example .env             # a dev .env is already provided (DEV_AUTH=1)
make run                         # http://localhost:8000/docs
```

Verify identity wiring: `curl -s localhost:8000/me` (works because `DEV_AUTH=1`). With real auth,
sign in via the accounts service to get a token, then call the BFF with `Authorization: Bearer …`.

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
  main.py           FastAPI app (health, /me, readiness, chat router)
  config.py         settings from env / .env (RS256 public key, agent/accounts URLs)
  auth.py           identity resolver (dev stub → RS256 token verify)
  security.py       decode_token (RS256 verification only — the BFF never issues)
  agent_client.py   async LangGraph client (chat proxy)
  accounts_client.py async accounts client (child-ownership check)
  routers/chat.py   threads, streaming turns, HITL resume
tests/              unit tests (mint tokens with an in-process RS256 keypair)
```
