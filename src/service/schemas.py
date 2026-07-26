"""Pydantic request/response models for the chat proxy.

The BFF no longer owns auth or family/child CRUD (that moved to the accounts service), so only the
chat surface remains: creating threads and driving streaming turns / HITL resume. Request models
validate and constrain client input at the edge.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# --- chat ---
class NewThreadRequest(BaseModel):
    # The child this conversation is about. Bound to the thread at creation and validated against
    # the caller's family; every turn on the thread then targets this child (see routers/chat.py).
    child_id: str | None = None


class NewThreadResponse(BaseModel):
    thread_id: str
    child_id: str | None = None


class TurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class ResumeRequest(BaseModel):
    approved: bool = False
    child: dict[str, Any] | None = None
    member: dict[str, Any] | None = None
