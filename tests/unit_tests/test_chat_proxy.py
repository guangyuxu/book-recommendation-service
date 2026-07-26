"""Chat proxy: thread ownership, context injection, SSE mapping, HITL, child validation.

The agent and the accounts service are replaced by fakes so these run offline. The fakes record
what they receive so we can assert identity is injected server-side (never client-supplied) and
that a client-supplied `child_id` is validated against the accounts service using the caller's own
token.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from langgraph_sdk.schema import StreamPart

from service.accounts_client import get_accounts_client
from service.agent_client import get_agent_client


class FakeAgent:
    def __init__(
        self,
        *,
        family_id: str,
        parts: list[StreamPart],
        child_id: str | None = None,
    ) -> None:
        self._family_id = family_id
        self._parts = parts
        # The child bound to the thread. Set on construction to simulate an already-bound thread,
        # or captured/updated when create_thread is called.
        self._child_id = child_id
        self.captured: dict[str, Any] = {}

    async def create_thread(
        self, *, family_id: str, child_id: str | None = None
    ) -> str:
        self.captured["create_family_id"] = family_id
        self.captured["create_child_id"] = child_id
        self._child_id = child_id
        return "thread-1"

    async def get_thread(self, thread_id: str) -> dict[str, Any]:
        return {
            "thread_id": thread_id,
            "metadata": {"family_id": self._family_id, "child_id": self._child_id},
        }

    async def set_thread_child(self, thread_id: str, *, child_id: str | None) -> None:
        self.captured["set_child_id"] = child_id
        self._child_id = child_id

    async def list_threads(
        self, *, family_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        return [
            {
                "thread_id": "thread-1",
                "metadata": {"family_id": family_id, "child_id": self._child_id},
            }
        ]

    async def get_history(
        self, thread_id: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        return [{"values": {"messages": []}}]

    def stream_turn(
        self, thread_id: str, *, message: str, context: dict[str, Any], **_: Any
    ) -> AsyncIterator[StreamPart]:
        self.captured["context"] = context
        self.captured["message"] = message
        return self._gen()

    def resume_turn(
        self, thread_id: str, *, resume_value: Any, context: dict[str, Any], **_: Any
    ) -> AsyncIterator[StreamPart]:
        self.captured["resume_value"] = resume_value
        self.captured["context"] = context
        return self._gen()

    async def _gen(self) -> AsyncIterator[StreamPart]:
        for part in self._parts:
            yield part


class FakeAccounts:
    """Stand-in for the accounts service's child-ownership check."""

    def __init__(self, *, owns: bool) -> None:
        self._owns = owns
        self.captured: dict[str, Any] = {}

    async def child_belongs_to_family(
        self, child_id: str, *, bearer_token: str
    ) -> bool:
        self.captured["child_id"] = child_id
        self.captured["bearer_token"] = bearer_token
        return self._owns

    async def healthz(self) -> bool:
        return True


_STREAM_PARTS = [
    StreamPart("messages/partial", {"content": "Hi"}),
    StreamPart("custom", {"node": "understand", "tokens": 5}),
    StreamPart("updates", {"understand": {"child_switch": {"to": "c1"}}}),
]

_INTERRUPT_PARTS = [
    StreamPart(
        "updates",
        {
            "__interrupt__": [
                {"value": {"type": "confirm_profile_writes", "question": "ok?"}}
            ]
        },
    ),
]


def _install_agent(client: Any, fake: FakeAgent) -> None:
    client.app.dependency_overrides[get_agent_client] = lambda: fake


def _install_accounts(client: Any, fake: FakeAccounts) -> None:
    client.app.dependency_overrides[get_accounts_client] = lambda: fake


def test_create_and_list_threads(auth: dict[str, Any]) -> None:
    client, headers = auth["client"], auth["headers"]
    fake = FakeAgent(family_id=auth["family_id"], parts=[])
    _install_agent(client, fake)
    _install_accounts(client, FakeAccounts(owns=True))
    created = client.post(
        "/chat/threads", headers=headers, json={"child_id": "child-abc"}
    )
    assert created.status_code == 201
    assert created.json()["thread_id"] == "thread-1"
    # The child is bound to the thread at creation and echoed back.
    assert created.json()["child_id"] == "child-abc"
    assert fake.captured["create_child_id"] == "child-abc"
    listed = client.get("/chat/threads", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["metadata"]["child_id"] == "child-abc"
    assert (
        client.get("/chat/threads/thread-1/history", headers=headers).status_code == 200
    )


def test_create_thread_without_child_is_allowed(auth: dict[str, Any]) -> None:
    client, headers = auth["client"], auth["headers"]
    fake = FakeAgent(family_id=auth["family_id"], parts=[])
    _install_agent(client, fake)
    # No child_id: valid (agent falls back to sole-child / in-conversation resolution).
    created = client.post("/chat/threads", headers=headers, json={})
    assert created.status_code == 201
    assert created.json()["child_id"] is None
    assert fake.captured["create_child_id"] is None


def test_stream_turn_injects_identity_and_maps_events(auth: dict[str, Any]) -> None:
    client, headers = auth["client"], auth["headers"]
    fake = FakeAgent(family_id=auth["family_id"], parts=_STREAM_PARTS)
    _install_agent(client, fake)

    resp = client.post(
        "/chat/threads/thread-1/messages",
        headers=headers,
        # A client-supplied family_id must be ignored (identity comes from the token).
        json={"message": "recommend a book", "family_id": "attacker"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "event: token" in body
    assert "event: usage" in body
    assert "event: update" in body
    assert "event: done" in body

    ctx = fake.captured["context"]
    assert ctx["family_id"] == auth["family_id"]
    assert ctx["family_member_id"] == auth["family_member_id"]
    assert ctx["child_id"] is None


def test_child_validated_at_create_and_injected_on_send(
    auth: dict[str, Any],
) -> None:
    client, headers = auth["client"], auth["headers"]
    fake = FakeAgent(family_id=auth["family_id"], parts=_STREAM_PARTS)
    _install_agent(client, fake)
    accounts = FakeAccounts(owns=True)
    _install_accounts(client, accounts)

    # Child is validated against the caller's family when the thread is created.
    created = client.post(
        "/chat/threads", headers=headers, json={"child_id": "child-xyz"}
    )
    assert created.status_code == 201
    # The BFF forwarded the caller's own token to accounts for the ownership check.
    assert accounts.captured["child_id"] == "child-xyz"
    assert accounts.captured["bearer_token"] == headers["Authorization"].split()[1]

    # Every turn on the bound thread injects that child from the thread metadata — the body
    # carries no child_id anymore.
    resp = client.post(
        "/chat/threads/thread-1/messages",
        headers=headers,
        json={"message": "hi"},
    )
    assert resp.status_code == 200
    assert fake.captured["context"]["child_id"] == "child-xyz"


def test_rebind_thread_child_validates_and_updates(auth: dict[str, Any]) -> None:
    client, headers = auth["client"], auth["headers"]
    fake = FakeAgent(family_id=auth["family_id"], parts=[], child_id="child-a")
    _install_agent(client, fake)
    accounts = FakeAccounts(owns=True)
    _install_accounts(client, accounts)

    resp = client.put(
        "/chat/threads/thread-1/child",
        headers=headers,
        json={"child_id": "child-b"},
    )
    assert resp.status_code == 200
    assert resp.json()["child_id"] == "child-b"
    # The new child was validated against the caller's family, then written to the thread.
    assert accounts.captured["child_id"] == "child-b"
    assert fake.captured["set_child_id"] == "child-b"
    # A subsequent turn now targets the re-bound child.
    turn = client.post(
        "/chat/threads/thread-1/messages", headers=headers, json={"message": "hi"}
    )
    assert turn.status_code == 200
    assert fake.captured["context"]["child_id"] == "child-b"


def test_rebind_rejects_foreign_child(auth: dict[str, Any]) -> None:
    client, headers = auth["client"], auth["headers"]
    _install_agent(
        client, FakeAgent(family_id=auth["family_id"], parts=[], child_id="child-a")
    )
    _install_accounts(client, FakeAccounts(owns=False))
    resp = client.put(
        "/chat/threads/thread-1/child",
        headers=headers,
        json={"child_id": "foreign-child"},
    )
    assert resp.status_code == 404


def test_cannot_rebind_another_familys_thread(auth: dict[str, Any]) -> None:
    client, headers = auth["client"], auth["headers"]
    _install_agent(client, FakeAgent(family_id="some-other-family", parts=[]))
    _install_accounts(client, FakeAccounts(owns=True))
    resp = client.put(
        "/chat/threads/thread-1/child",
        headers=headers,
        json={"child_id": "child-b"},
    )
    assert resp.status_code == 404


def test_interrupt_surfaces_confirmation_request(auth: dict[str, Any]) -> None:
    client, headers = auth["client"], auth["headers"]
    _install_agent(
        client, FakeAgent(family_id=auth["family_id"], parts=_INTERRUPT_PARTS)
    )
    resp = client.post(
        "/chat/threads/thread-1/messages",
        headers=headers,
        json={"message": "save my child's profile"},
    )
    assert "event: confirmation_request" in resp.text
    assert "confirm_profile_writes" in resp.text


def test_resume_passes_decision(auth: dict[str, Any]) -> None:
    client, headers = auth["client"], auth["headers"]
    fake = FakeAgent(family_id=auth["family_id"], parts=_STREAM_PARTS)
    _install_agent(client, fake)
    resp = client.post(
        "/chat/threads/thread-1/resume",
        headers=headers,
        json={"approved": True},
    )
    assert resp.status_code == 200
    assert fake.captured["resume_value"] == {"approved": True}


def test_resume_injects_thread_child(auth: dict[str, Any]) -> None:
    # Regression: resume must target the thread's bound child, not None.
    client, headers = auth["client"], auth["headers"]
    fake = FakeAgent(
        family_id=auth["family_id"], parts=_STREAM_PARTS, child_id="child-9"
    )
    _install_agent(client, fake)
    resp = client.post(
        "/chat/threads/thread-1/resume",
        headers=headers,
        json={"approved": True},
    )
    assert resp.status_code == 200
    assert fake.captured["context"]["child_id"] == "child-9"


def test_cannot_use_another_familys_thread(auth: dict[str, Any]) -> None:
    client, headers = auth["client"], auth["headers"]
    # The thread's metadata belongs to a different family.
    _install_agent(
        client, FakeAgent(family_id="some-other-family", parts=_STREAM_PARTS)
    )
    resp = client.post(
        "/chat/threads/thread-1/messages", headers=headers, json={"message": "hi"}
    )
    assert resp.status_code == 404


def test_cannot_target_another_familys_child(auth: dict[str, Any]) -> None:
    client, headers = auth["client"], auth["headers"]
    _install_agent(client, FakeAgent(family_id=auth["family_id"], parts=_STREAM_PARTS))
    # Accounts says the child does NOT belong to the caller's family: binding is rejected at
    # thread creation, so the foreign child never reaches a conversation.
    _install_accounts(client, FakeAccounts(owns=False))
    resp = client.post(
        "/chat/threads",
        headers=headers,
        json={"child_id": "foreign-child"},
    )
    assert resp.status_code == 404


@pytest.fixture(autouse=True)
def _clear_overrides(client: Any) -> Any:
    yield
    client.app.dependency_overrides.clear()
