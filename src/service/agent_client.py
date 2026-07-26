"""Async client wrapping the LangGraph agent (TODO #2).

A thin seam over `langgraph_sdk` so the chat router depends on a small, mockable surface. Identity
is injected here from the server-derived `AppContext` (`context=`); the client never lets the
caller set `family_id`. Threads are tagged with `family_id` in their metadata so conversations can
be listed and ownership-checked per family (#5).

Exposed as the FastAPI dependency `get_agent_client`; tests override it with a fake.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from functools import lru_cache
from typing import Any

from langgraph_sdk import get_client
from langgraph_sdk.schema import StreamMode, StreamPart

from .config import get_settings

# Stream modes we consume from the agent: token deltas, per-node state deltas, and custom usage
# events (`{node, tokens}`). See the agent's usage_tracker / state docs.
DEFAULT_STREAM_MODE: tuple[StreamMode, ...] = ("messages", "updates", "custom")


class AgentClient:
    """Minimal async facade over the LangGraph Server run/thread APIs."""

    def __init__(
        self,
        *,
        url: str,
        graph_name: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._client = get_client(url=url, headers=headers)
        self._graph = graph_name

    async def create_thread(
        self, *, family_id: str, child_id: str | None = None
    ) -> str:
        # `child_id` binds the conversation to one child for its whole lifetime; every turn reads it
        # back from this metadata (the BFF holds no DB). `family_id` scopes ownership/listing (#5).
        thread = await self._client.threads.create(
            metadata={"family_id": family_id, "child_id": child_id}
        )
        return str(thread["thread_id"])

    async def get_thread(self, thread_id: str) -> dict[str, Any]:
        return dict(await self._client.threads.get(thread_id))

    async def set_thread_child(self, thread_id: str, *, child_id: str | None) -> None:
        # Re-bind the conversation to a different child (the agent switched mid-conversation, and the
        # user confirmed). `threads.update` MERGES metadata, so `family_id` is preserved.
        await self._client.threads.update(thread_id, metadata={"child_id": child_id})

    async def list_threads(
        self, *, family_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        threads = await self._client.threads.search(
            metadata={"family_id": family_id}, limit=limit
        )
        return [dict(t) for t in threads]

    async def get_history(
        self, thread_id: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        states = await self._client.threads.get_history(thread_id, limit=limit)
        return [dict(s) for s in states]

    def stream_turn(
        self,
        thread_id: str,
        *,
        message: str,
        context: Mapping[str, Any],
        stream_mode: Sequence[StreamMode] = DEFAULT_STREAM_MODE,
    ) -> AsyncIterator[StreamPart]:
        """Start a run for `message` and stream the agent's events."""
        payload: dict[str, Any] = {"messages": [{"role": "user", "content": message}]}
        return self._client.runs.stream(
            thread_id,
            self._graph,
            input=payload,
            context=dict(context),
            stream_mode=list(stream_mode),
        )

    def resume_turn(
        self,
        thread_id: str,
        *,
        resume_value: Any,
        context: Mapping[str, Any],
        stream_mode: Sequence[StreamMode] = DEFAULT_STREAM_MODE,
    ) -> AsyncIterator[StreamPart]:
        """Resume an interrupted run on the same thread with the HITL decision."""
        return self._client.runs.stream(
            thread_id,
            self._graph,
            command={"resume": resume_value},
            context=dict(context),
            stream_mode=list(stream_mode),
        )


@lru_cache
def get_agent_client() -> AgentClient:
    """Return the process-wide agent client (FastAPI dependency; overridden in tests)."""
    settings = get_settings()
    return AgentClient(url=settings.agent_url, graph_name=settings.agent_graph_name)
