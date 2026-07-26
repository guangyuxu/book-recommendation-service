"""Token verification: the BFF only decodes RS256 tokens (it never issues them)."""

from __future__ import annotations

import jwt
import pytest

from service.config import Settings
from service.security import decode_token

from .conftest import (
    AUDIENCE,
    ISSUER,
    TEST_PRIVATE_KEY,
    TEST_PUBLIC_KEY,
    make_keypair,
    sign_token,
)


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"jwt_public_key": TEST_PUBLIC_KEY}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_decode_valid_token_returns_claims() -> None:
    token = sign_token(family_id="fam-1", family_member_id="mem-1")
    claims = decode_token(token, settings=_settings())
    assert claims["family_id"] == "fam-1"
    assert claims["family_member_id"] == "mem-1"


def test_decode_rejects_token_signed_by_another_key() -> None:
    other_priv, _ = make_keypair()
    token = sign_token(family_id="f", family_member_id="m", private_key=other_priv)
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(token, settings=_settings())


def test_decode_rejects_wrong_issuer() -> None:
    token = sign_token(family_id="f", family_member_id="m", issuer="someone-else")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(token, settings=_settings())


def test_decode_rejects_wrong_audience() -> None:
    token = sign_token(family_id="f", family_member_id="m", audience="someone-else")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(token, settings=_settings())


def test_decode_rejects_expired_token() -> None:
    token = sign_token(family_id="f", family_member_id="m", ttl_seconds=-1)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(token, settings=_settings())


def test_claims_contract_is_stable() -> None:
    # The BFF verifier and the accounts issuer must agree on iss/aud.
    assert ISSUER == "book-recommendation-accounts"
    assert AUDIENCE == "book-recommendation"
    assert TEST_PRIVATE_KEY.startswith("-----BEGIN PRIVATE KEY-----")
