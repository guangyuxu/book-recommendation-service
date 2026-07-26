# Backend (BFF) — Feature Backlog

This service is the **pass-through backend** in front of the book-recommendation agent
(LangGraph). It authenticates the caller, derives identity, injects it into the agent run
context, streams responses back, drives the HITL confirmation flow, and exposes usage/profile
HTTP endpoints. It shares the agent's Postgres and DB tooling (Advanced Alchemy + SQLAlchemy +
psycopg).

Grounded in the agent's actual contract: run **context** (`family_id` / `family_member_id` /
`child_id`), `thread_id`, stream modes (`messages` / `updates` / `custom`), the `interrupt()`
HITL gate (`confirmation_request` → resume with `Command(resume=...)`), `token_usage_record`,
`child_switch`, and strict `family_id` scoping.

Legend: `[ ]` todo · `[~]` scaffolded · `[x]` done

---

## A. Core proxy responsibilities (MVP)

### 1. Auth & identity derivation (ROADMAP B1)
- [~] Pluggable identity resolver (`service.auth.get_identity`) — dev stub done.
- [x] Real token verification (Bearer JWT / session): derive `family_id` / `family_member_id`
      from verified claims. Never trust client-supplied ids. (`service.security` + `auth.py`)
- [~] Resolve/select active `child_id` — accepted per-request (chat body / policy refs) and
      validated against the family; session-level "active child" selection not persisted yet.
- [x] Authorization: confirm the member belongs to the family (token-derived; thread ownership
      checked via thread metadata `family_id`).
- [x] Local JWT path (self-signed HS256, `JWT_SECRET`) exercises the real verify code offline.

### 2. Agent invocation / orchestration
- [x] LangGraph client (`langgraph-sdk`) against `AGENT_URL` (`service.agent_client`):
      create/continue threads, invoke/resume runs.
- [x] Inject `AppContext` (identity → `to_context()`) on every run via `context=`.
- [x] `thread_id` management: a conversation IS a LangGraph thread (create/list/history via SDK).
- [~] Pass the user message as input `messages`; explicit `run_id` / `turn_id` tracking TBD.

### 3. Streaming passthrough (SSE)
- [x] Consume agent stream (`messages` / `updates` / `custom`) and re-emit as SSE (`routers/chat`).
- [x] Forward token stream, per-node `{node, tokens}` usage events, node/status updates.
- [~] Client-disconnect handling + heartbeats done (sse-starlette); backpressure TBD.

### 4. HITL confirmation flow
- [x] Detect `interrupt()` / `confirmation_request` (the `__interrupt__` update); surface payload.
- [x] Accept/Reject; resume the SAME `thread_id` with `command={"resume": ...}`.
- [ ] Handle pending-confirmation timeout / abandonment.

### 5. Conversation / thread management
- [x] New conversation, fetch history, list conversations (SDK; family-scoped by thread metadata).
- [x] Map frontend conversation ↔ `thread_id` (identity mapping — the thread id is the id).
- [x] Pass through `child_switch` (forwarded as an `update` SSE event).

## B. Data & family management (MVP-likely)

### 6. Family / member / child / reading-profile / policy CRUD
- [x] Signup creates the family + primary member (unique `email` + `password_hash`); onboarding +
      management endpoints for members / children / reading profiles / policies (`routers/auth`,
      `routers/family`).
- [x] Every read/write scoped by `family_id` via family-scoped repositories (`get_in_family`).
- [x] Decision: **duplicate** the agent's models here (the subset #6 needs), mirroring columns so
      both services share one `book_agent` schema. `service/db/models` holds family + child models;
      the agent's auth-less schema is extended with `email`/`password_hash` on `family_member`.

### 7. Recommendation history / reading tracking
- [ ] Read `recommendation_session` + items (agent persists these); expose history endpoints.

### 8. Usage endpoint (ROADMAP B4 / #3)
- [ ] `GET` per-turn usage keyed by `turn_id`: `GROUP BY node`, `SUM(input+output)` →
      `{ per_node: [{node, tokens}], total }`. Read-only over `token_usage_record`.

## C. Protection & governance

### 9. Rate limiting & edge validation (ROADMAP B2)
- [ ] Per-family / per-member rate limiting.
- [ ] Request size caps, encoding/schema validation before starting a run.

### 10. Cost governance / quotas (ROADMAP B3)
- [ ] Pre-run budget/quota check; circuit-break (429/402) when over budget. Uses #8's data.

## D. Cross-cutting / ops
- [x] Health probe (`/healthz`).
- [x] Readiness probe (`/readyz`: checks DB `SELECT 1` + agent `/ok` reachability).
- [~] CORS (configured from `CORS_ORIGINS`).
- [x] PII-safe structured logging (`service.logging`: request-id formatter, exception type only).
- [~] Correlation ids (`X-Request-Id` middleware, echoed + logged); LangSmith trace propagation TBD.
- [x] Uniform error envelope (`{"error": {code, message, request_id}}` handlers in `main`).
- [x] Config/secrets via env (`service.config`; `JWT_SECRET` required outside dev-auth).

## Later (non-MVP)
- [ ] Feedback capture (👍/👎, accepted/finished) → ROADMAP #4.
- [ ] Internal cost projection (per-`model_id` price table; never shown to users).
- [ ] Notifications / email / push; audit log.

---

## Key decisions (locked / open)
- **Framework**: FastAPI + uv. ✅ locked.
- **DB**: shares the agent's Postgres, same tooling (Advanced Alchemy + SQLAlchemy + psycopg). ✅
- **Auth (local)**: dev-auth stub (`DEV_AUTH=1`, fixed identity), same resolver seam as prod. ✅
- **Realtime**: SSE (not WebSocket) for the MVP. (revisit if bidirectional needed)
- **ORM model sharing**: **duplicate** the agent's models here (subset), mirroring columns for one
  shared `book_agent` schema; `family_member` gains `email`/`password_hash` for signup. ✅ locked.
- **k8s / deploy infra**: handled separately, later. (intentionally not in this repo yet)
