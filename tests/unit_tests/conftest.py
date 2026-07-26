"""Hermetic test setup for the verify-only BFF: an RS256 keypair and common fixtures.

The BFF no longer connects to a DB or issues tokens — it VERIFIES tokens issued by the accounts
service. Tests therefore mint tokens with an in-process RS256 keypair (standing in for accounts)
and hand the app only the PUBLIC key via `JWT_PUBLIC_KEY`. `DEV_AUTH=0` exercises the real
verification path. `setdefault` lets an outer environment override.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "book-recommendation-accounts"
AUDIENCE = "book-recommendation"


def make_keypair() -> tuple[str, str]:
    """Return a fresh (private_pem, public_pem) RS256 keypair as PEM strings."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


# The keypair the BFF trusts for this test session. Private key stays in the test (accounts' role);
# the app only ever sees the public key.
TEST_PRIVATE_KEY, TEST_PUBLIC_KEY = make_keypair()

os.environ.setdefault("JWT_PUBLIC_KEY", TEST_PUBLIC_KEY)
os.environ.setdefault("DEV_AUTH", "0")


def sign_token(
    *,
    family_id: str,
    family_member_id: str,
    private_key: str = TEST_PRIVATE_KEY,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    ttl_seconds: int = 3600,
) -> str:
    """Mint an RS256 access token the way the accounts service would."""
    now = datetime.now(UTC)
    claims = {
        "sub": family_member_id,
        "family_id": family_id,
        "family_member_id": family_member_id,
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(claims, private_key, algorithm="RS256")


@pytest.fixture(autouse=True)
def _reset_caches() -> Iterator[None]:
    from service.accounts_client import get_accounts_client
    from service.config import get_settings

    get_settings.cache_clear()
    get_accounts_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_accounts_client.cache_clear()


@pytest.fixture
def client() -> Any:
    from fastapi.testclient import TestClient

    from service.main import create_app

    return TestClient(create_app())


@pytest.fixture
def auth(client: Any) -> dict[str, Any]:
    """A signed-in caller: a valid token + the ids it carries (no DB, no signup)."""
    family_id = "16555532-69b5-411e-8526-e0b321fbcfea"
    family_member_id = "659c1323-f47a-40eb-a0fe-5fb83f47c9c9"
    token = sign_token(family_id=family_id, family_member_id=family_member_id)
    return {
        "client": client,
        "headers": {"Authorization": f"Bearer {token}"},
        "family_id": family_id,
        "family_member_id": family_member_id,
    }
