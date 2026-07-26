# Project Rules for Claude Code

This is the **pass-through backend (BFF)** in front of the book-recommendation agent. It
**verifies** the caller's access token (RS256, with the accounts service's public key), derives
identity, injects it into the agent run context, streams responses back, and drives the HITL
confirmation flow. It **holds no database connection and no private key**: token issuance
(signup/login) and family/child CRUD live in the sibling **accounts service**
(`book-recommendation-accounts`); the BFF calls the accounts service when it must confirm a
client-supplied child belongs to the caller's family. The rules below mirror the sibling repos so
all projects hold one standard.

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

- The BFF has no DB; it does not read child/member rows directly. When an endpoint acts on a
  client-supplied `child_id`, it **must confirm that child belongs to the caller's `family_id`**
  before injecting it into the agent context — done by asking the accounts service with the
  caller's own token (which applies the family scope). Never pass a client-supplied id straight
  through to the agent without that confirmation.

## Testing rules

- Endpoints that resolve identity must have a test that a caller cannot reach another family's
  data by passing a foreign id (e.g. a foreign `child_id` in a turn → 404, with the accounts
  ownership check faked).

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
