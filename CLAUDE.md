# Project Rules for Claude Code

This is the **pass-through backend (BFF)** in front of the book-recommendation agent. It
authenticates the caller, derives identity, injects it into the agent run context, streams
responses back, drives the HITL confirmation flow, and exposes usage/profile HTTP endpoints. It
shares the agent's Postgres and its DB tooling. The rules below mirror the agent repo so the two
projects hold one standard.

## PII & Security

This project stores and processes children's personal data (name, birthday, gender, reading
level). Treat all child/family data as high-sensitivity PII.

### Logging rules

- **Never log PII values in `logger.*` calls.** This includes: child names, birth dates,
  genders, reading interests, goals, user messages, family member names, and any field from
  `ChildProfile`, `FamilyMember`, `ChildReadingProfile`, `FamilyReadingPolicy`.
- When logging exceptions that may have touched DB rows or user input, log only the exception
  **type** (`type(exc).__name__`), never the full exception object or message.
  ```python
  # WRONG
  logger.warning("failed: %s", exc)
  # RIGHT
  logger.warning("failed: %s", type(exc).__name__)
  ```
- Safe to log: IDs (UUIDs), capability names, intent names, operation names, row counts,
  boolean flags.

### Authentication & identity rules

- **Identity is derived server-side, never trusted from the client.** Verify the caller's token,
  derive `family_id` / `family_member_id` from the verified claims, and inject them into the
  agent's run context. A client must never be able to set `family_id` / `family_member_id` /
  `child_id` directly — the agent trusts whatever context this service passes, so this service is
  the authorization gate.
- The dev-auth stub (`DEV_AUTH=1`) is for local only and must be disabled in any deployed
  environment; it still flows identity through the same resolver seam as real auth.

### Authorization rules

- Every repository read that takes a `child_id` or `member_id` **must also filter by
  `family_id`**. A query scoped only to `child_id` is a cross-family data leak.
- Any endpoint that acts on a child/member must confirm that child/member belongs to the
  caller's `family_id` before doing anything.

## Testing rules

- New repository methods that read data must have a cross-family isolation test: seed data
  under family A, query with family B's id, assert empty result.
- Endpoints that resolve identity must have a test that a caller cannot reach another family's
  data by passing a foreign id.

## Build & verification

The Makefile `CHECKS` section is the single source of truth for verification. Nothing restates
those commands: GitHub Actions (`.github/workflows/ci.yml`) runs `make ci` verbatim, and the
pre-commit hooks (`.pre-commit-config.yaml`) run `make check` on commit and `make ci` on push. So
local and CI cannot drift.

After every code change, run the everyday gate and make sure it is green before treating the work
as done. Do NOT report a task as complete while any check fails.

```bash
make check   # lint (ruff check + ruff format --diff + mypy + codespell) + test — fast, offline
```

Before pushing, run the full CI mirror (lint + tests under coverage, with a `fail_under` floor):

```bash
make ci      # what GitHub Actions runs verbatim: lint + coverage (offline)
```

If `make check` reports formatting diffs, run `make format` to auto-fix them. Optional: install
the local hooks once with `uv run pre-commit install` (runs `make check` + gitleaks on commit,
`make ci` on push). Focused subsets while iterating: `make lint`, `make test`, `make spell_check`.

Security tooling (does not block the code gate): ruff's `S` (flake8-bandit) rules run inside
`lint`; `make audit` (pip-audit) runs on a schedule (`.github/workflows/audit.yml`); gitleaks
scans for secrets in pre-commit and in CI; Dependabot opens dependency-update PRs.
