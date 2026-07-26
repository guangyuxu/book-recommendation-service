"""Chat proxy: threads, streaming turns, and the HITL confirmation flow (TODO #2–#5).

A conversation IS a LangGraph thread. This router creates/lists threads (tagged with the caller's
`family_id`), streams a turn's agent events to the frontend as SSE, surfaces the agent's single
`interrupt()` as a `confirmation_request` event, and resumes the same thread with the caller's
Accept/Reject decision. Identity is always injected server-side via the agent client.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from httpx import HTTPError
from langgraph_sdk.schema import StreamPart
from sse_starlette.sse import EventSourceResponse

from ..accounts_client import AccountsClient, get_accounts_client
from ..agent_client import AgentClient, get_agent_client
from ..auth import Identity, get_identity
from ..config import Settings, get_settings
from ..schemas import (
    NewThreadRequest,
    NewThreadResponse,
    ResumeRequest,
    TurnRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")


def _sse(event: str, data: Any) -> dict[str, str]:
    return {"event": event, "data": json.dumps(data, default=str)}


def _bearer(authorization: str | None) -> str | None:
    scheme, _, token = (authorization or "").partition(" ")
    return token if scheme.lower() == "bearer" and token else None


async def _validate_child(
    accounts: AccountsClient,
    child_id: str | None,
    *,
    bearer_token: str | None,
    dev_auth: bool,
) -> str | None:
    """Ensure a client-supplied active `child_id` belongs to the caller's family.

    The BFF no longer reads the DB, so it asks the accounts service with the caller's own token
    (accounts applies its family-scoped guard). In dev-auth (local only) there is no real token, so
    the check is skipped and the id is trusted.
    """
    if child_id is None:
        return None
    if dev_auth:
        return child_id
    if bearer_token is None or not await accounts.child_belongs_to_family(
        child_id, bearer_token=bearer_token
    ):
        raise _NOT_FOUND
    return child_id


async def _require_owned_thread(
    agent: AgentClient, thread_id: str, family_id: str
) -> dict[str, Any]:
    """Return the thread's metadata, or 404 unless it exists and belongs to the caller's family.

    Callers read the thread's bound `child_id` from the returned metadata (the child is fixed at
    creation, so every turn/resume on the thread targets the same child).
    """
    try:
        thread = await agent.get_thread(thread_id)
    except HTTPError:
        raise _NOT_FOUND from None
    metadata: dict[str, Any] = thread.get("metadata") or {}
    if metadata.get("family_id") != family_id:
        raise _NOT_FOUND
    return metadata


def _translate(part: StreamPart) -> dict[str, str] | None:
    """Map one agent StreamPart to an SSE event (or None to drop it)."""
    event, data = part.event, part.data
    if event.startswith("messages"):
        return _sse("token", data)
    if event == "custom":
        return _sse("usage", data)
    if event == "updates":
        if isinstance(data, dict) and "__interrupt__" in data:
            interrupts = data["__interrupt__"]
            payload: Any = interrupts
            if isinstance(interrupts, list) and interrupts:
                first = interrupts[0]
                payload = (
                    first.get("value", first) if isinstance(first, dict) else first
                )
            return _sse("confirmation_request", payload)
        return _sse("update", data)
    if event == "error":
        return _sse("error", data)
    return None


async def _relay(
    request: Request, stream: AsyncIterator[StreamPart]
) -> AsyncIterator[dict[str, str]]:
    """Re-emit an agent stream as SSE, honoring client disconnect. PII-safe on error."""
    try:
        async for part in stream:
            if await request.is_disconnected():
                break
            translated = _translate(part)
            if translated is not None:
                yield translated
    except HTTPError as exc:
        logger.warning("agent stream failed: %s", type(exc).__name__)
        yield _sse("error", {"message": "agent stream failed"})
    yield _sse("done", {})


# --- threads (#5) ---
@router.post(
    "/threads", response_model=NewThreadResponse, status_code=status.HTTP_201_CREATED
)
async def create_thread(
    body: NewThreadRequest | None = None,
    authorization: str | None = Header(default=None),
    identity: Identity = Depends(get_identity),
    agent: AgentClient = Depends(get_agent_client),
    accounts: AccountsClient = Depends(get_accounts_client),
    settings: Settings = Depends(get_settings),
) -> NewThreadResponse:
    # Bind the conversation to a child now (validated against the caller's family), so every later
    # turn/resume reads it from the thread — the client can't swap children mid-conversation.
    child_id = await _validate_child(
        accounts,
        body.child_id if body else None,
        bearer_token=_bearer(authorization),
        dev_auth=settings.dev_auth,
    )
    thread_id = await agent.create_thread(
        family_id=identity.family_id, child_id=child_id
    )
    return NewThreadResponse(thread_id=thread_id, child_id=child_id)


@router.get("/threads")
async def list_threads(
    identity: Identity = Depends(get_identity),
    agent: AgentClient = Depends(get_agent_client),
) -> list[dict[str, Any]]:
    return await agent.list_threads(family_id=identity.family_id)


@router.put("/threads/{thread_id}/child", response_model=NewThreadResponse)
async def set_thread_child(
    thread_id: str,
    body: NewThreadRequest,
    authorization: str | None = Header(default=None),
    identity: Identity = Depends(get_identity),
    agent: AgentClient = Depends(get_agent_client),
    accounts: AccountsClient = Depends(get_accounts_client),
    settings: Settings = Depends(get_settings),
) -> NewThreadResponse:
    # Re-bind an owned thread to a different child after the user confirms an agent-side switch.
    # Ownership + child-in-family are both enforced (the client can't bind a foreign child).
    await _require_owned_thread(agent, thread_id, identity.family_id)
    child_id = await _validate_child(
        accounts,
        body.child_id,
        bearer_token=_bearer(authorization),
        dev_auth=settings.dev_auth,
    )
    await agent.set_thread_child(thread_id, child_id=child_id)
    return NewThreadResponse(thread_id=thread_id, child_id=child_id)


@router.get("/threads/{thread_id}/history")
async def thread_history(
    thread_id: str,
    identity: Identity = Depends(get_identity),
    agent: AgentClient = Depends(get_agent_client),
) -> list[dict[str, Any]]:
    await _require_owned_thread(agent, thread_id, identity.family_id)
    return await agent.get_history(thread_id)


# --- streaming turn (#2/#3) ---
@router.post("/threads/{thread_id}/messages")
async def send_message(
    thread_id: str,
    body: TurnRequest,
    request: Request,
    identity: Identity = Depends(get_identity),
    agent: AgentClient = Depends(get_agent_client),
) -> EventSourceResponse:
    metadata = await _require_owned_thread(agent, thread_id, identity.family_id)
    context = {
        "family_id": identity.family_id,
        "family_member_id": identity.family_member_id,
        "child_id": metadata.get("child_id"),
    }
    stream = agent.stream_turn(thread_id, message=body.message, context=context)
    return EventSourceResponse(_relay(request, stream))


# --- HITL resume (#4) ---
@router.post("/threads/{thread_id}/resume")
async def resume(
    thread_id: str,
    body: ResumeRequest,
    request: Request,
    identity: Identity = Depends(get_identity),
    agent: AgentClient = Depends(get_agent_client),
) -> EventSourceResponse:
    metadata = await _require_owned_thread(agent, thread_id, identity.family_id)
    context = {
        "family_id": identity.family_id,
        "family_member_id": identity.family_member_id,
        "child_id": metadata.get("child_id"),
    }
    resume_value = body.model_dump(exclude_none=True)
    stream = agent.resume_turn(thread_id, resume_value=resume_value, context=context)
    return EventSourceResponse(_relay(request, stream))
