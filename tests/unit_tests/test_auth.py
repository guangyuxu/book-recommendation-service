"""The BFF's identity seam: verify accounts-issued tokens, fail closed, honor the dev stub."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from service.config import Settings, get_settings
from service.main import create_app

from .conftest import TEST_PUBLIC_KEY, make_keypair, sign_token


def test_me_accepts_valid_token(auth: dict[str, Any]) -> None:
    resp = auth["client"].get("/me", headers=auth["headers"])
    assert resp.status_code == 200
    assert resp.json()["family_id"] == auth["family_id"]
    assert resp.json()["family_member_id"] == auth["family_member_id"]


def test_me_requires_a_bearer_token(client: Any) -> None:
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Basic x"}).status_code == 401
    assert (
        client.get("/me", headers={"Authorization": "Bearer not.a.jwt"}).status_code
        == 401
    )


def test_me_rejects_token_from_an_untrusted_issuer_key(client: Any) -> None:
    # A token signed by a key the BFF does NOT trust must be rejected (forged token).
    forged_priv, _ = make_keypair()
    token = sign_token(family_id="f", family_member_id="m", private_key=forged_priv)
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_me_fails_closed_without_dev_auth() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(  # type: ignore[call-arg]
        dev_auth=False, jwt_public_key=TEST_PUBLIC_KEY
    )
    resp = TestClient(app).get("/me")
    assert resp.status_code == 401


def test_me_returns_fixed_identity_in_dev_auth() -> None:
    app = create_app()
    dev = Settings(  # type: ignore[call-arg]
        dev_auth=True,
        dev_family_id="fam-1",
        dev_family_member_id="mem-1",
        dev_child_id="child-1",
    )
    app.dependency_overrides[get_settings] = lambda: dev
    resp = TestClient(app).get("/me")
    assert resp.status_code == 200
    assert resp.json() == {
        "family_id": "fam-1",
        "family_member_id": "mem-1",
        "child_id": "child-1",
    }


def test_client_cannot_override_identity_via_query() -> None:
    app = create_app()
    dev = Settings(dev_auth=True, dev_family_id="fam-real")  # type: ignore[call-arg]
    app.dependency_overrides[get_settings] = lambda: dev
    resp = TestClient(app).get("/me?family_id=fam-attacker")
    assert resp.status_code == 200
    assert resp.json()["family_id"] == "fam-real"
