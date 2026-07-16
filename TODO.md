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
- [ ] Real token verification (Bearer JWT / session): derive `family_id` / `family_member_id`
      from verified claims. Never trust client-supplied ids.
- [ ] Resolve/select active `child_id` (from request or session).
- [ ] Authorization: confirm the member belongs to the family (this service is the gate).
- [ ] Local JWT path (self-signed) to exercise the real verify code offline before a real IdP.

### 2. Agent invocation / orchestration
- [ ] LangGraph client (SDK/REST) against `AGENT_URL`: create/continue threads, invoke runs.
- [ ] Inject `AppContext` (identity → `to_context()`) on every run.
- [ ] `thread_id` management: map a conversation to a LangGraph thread; persist/lookup.
- [ ] Pass the user message as input `messages`; track `run_id` / `turn_id`.

### 3. Streaming passthrough (SSE)
- [ ] Consume agent stream (`messages` / `updates` / `custom`) and re-emit as SSE to the frontend.
- [ ] Forward token stream, per-node `{node, tokens}` usage events, node/status updates.
- [ ] Client-disconnect handling, heartbeats, backpressure.

### 4. HITL confirmation flow
- [ ] Detect `interrupt()` / `confirmation_request` from the run; surface payload to frontend.
- [ ] Accept Accept/Reject; resume the SAME `thread_id` with `Command(resume=...)`.
- [ ] Handle pending-confirmation timeout / abandonment.

### 5. Conversation / thread management
- [ ] New conversation, fetch history, list conversations.
- [ ] Map frontend conversation ↔ `thread_id`.
- [ ] Pass through `child_switch` (frontend avatar swap + undo).

## B. Data & family management (MVP-likely)

### 6. Family / member / child / reading-profile / policy CRUD
- [ ] Onboarding + management endpoints (add child, edit profile, set policies) outside a chat turn.
- [ ] Every read/write scoped by `family_id` (reuse family-scoped repositories).
- [ ] Decision: **share the agent's ORM models** (import from the agent package as a path/VCS
      dependency) vs. **duplicate** them here. `service.db.base` mirrors the agent's infra;
      `service/db/models` is an empty placeholder until this is settled.

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
- [ ] Readiness probe (checks DB / agent reachability).
- [~] CORS (configured from `CORS_ORIGINS`).
- [ ] PII-safe structured logging (mirror the agent's rules: no PII, exception type only).
- [ ] Correlation ids; propagate tracing to LangSmith.
- [ ] Uniform error envelope.
- [ ] Config/secrets via env / Secrets Manager.

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
- **ORM model sharing**: share vs. duplicate the agent's models — **OPEN** (see #6).
- **k8s / deploy infra**: handled separately, later. (intentionally not in this repo yet)
