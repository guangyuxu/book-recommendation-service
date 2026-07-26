"""Cross-cutting ops: readiness (agent + accounts), error envelope, correlation id."""

from __future__ import annotations

from typing import Any

import pytest

from service import main


class _FakeAccounts:
    def __init__(self, ok: bool) -> None:
        self._ok = ok

    async def healthz(self) -> bool:
        return self._ok


async def _agent_up(_: str) -> bool:
    return True


async def _agent_down(_: str) -> bool:
    return False


def test_healthz(client: Any) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_ok(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "_check_agent", _agent_up)
    monkeypatch.setattr(main, "get_accounts_client", lambda: _FakeAccounts(True))
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ok",
        "checks": {"agent": True, "accounts": True},
    }


def test_readyz_degraded_without_agent(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "_check_agent", _agent_down)
    monkeypatch.setattr(main, "get_accounts_client", lambda: _FakeAccounts(True))
    resp = client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"] == {"agent": False, "accounts": True}


def test_readyz_degraded_without_accounts(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "_check_agent", _agent_up)
    monkeypatch.setattr(main, "get_accounts_client", lambda: _FakeAccounts(False))
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["checks"] == {"agent": True, "accounts": False}


def test_error_envelope_shape(client: Any) -> None:
    resp = client.get("/me")  # no token -> 401 through the envelope handler
    assert resp.status_code == 401
    err = resp.json()["error"]
    assert err["code"] == 401
    assert "request_id" in err
    assert err["request_id"] == resp.headers["X-Request-Id"]


def test_correlation_id_is_echoed(client: Any) -> None:
    resp = client.get("/healthz", headers={"X-Request-Id": "trace-123"})
    assert resp.headers["X-Request-Id"] == "trace-123"


def test_correlation_id_is_generated_when_absent(client: Any) -> None:
    resp = client.get("/healthz")
    assert resp.headers.get("X-Request-Id")
