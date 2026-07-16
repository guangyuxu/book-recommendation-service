"""Smoke tests for the app wiring: health probe and the dev-auth identity seam.

Offline -- no DB, no network. They pin (1) the liveness endpoint and (2) that identity is
resolved server-side: fail-closed (401) without dev-auth, fixed identity with it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from service.config import Settings, get_settings
from service.main import create_app


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    # get_settings is lru_cached; clear it so per-test env/overrides take effect.
    get_settings.cache_clear()


def test_healthz_is_ok() -> None:
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_me_fails_closed_without_dev_auth() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(dev_auth=False)
    resp = TestClient(app).get("/me")
    assert resp.status_code == 401


def test_me_returns_fixed_identity_in_dev_auth() -> None:
    app = create_app()
    dev = Settings(
        dev_auth=True,
        dev_family_id="fam-1",
        dev_family_member_id="mem-1",
        dev_child_id="child-1",
    )
    # Override both the app settings and the auth dependency's settings.
    app.dependency_overrides[get_settings] = lambda: dev
    resp = TestClient(app).get("/me")
    assert resp.status_code == 200
    assert resp.json() == {
        "family_id": "fam-1",
        "family_member_id": "mem-1",
        "child_id": "child-1",
    }


def test_client_cannot_override_identity_via_query_or_body() -> None:
    # Identity is derived server-side; client-supplied ids must be ignored.
    app = create_app()
    dev = Settings(dev_auth=True, dev_family_id="fam-real")
    app.dependency_overrides[get_settings] = lambda: dev
    resp = TestClient(app).get("/me?family_id=fam-attacker")
    assert resp.status_code == 200
    assert resp.json()["family_id"] == "fam-real"


def test_cors_origin_list_parsing() -> None:
    s = Settings(cors_origins="http://a.com, http://b.com ,")
    assert s.cors_origin_list == ["http://a.com", "http://b.com"]
