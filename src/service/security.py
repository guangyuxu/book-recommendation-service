"""Session-token (JWT) verification.

The BFF is a token VERIFIER only. It does not issue tokens, hash passwords, or hold any private
key — the accounts service owns issuance. Here we only verify RS256 access tokens with the
accounts service's PUBLIC key and check the `iss`/`aud` claims contract.
"""

from __future__ import annotations

from typing import Any

import jwt

from .config import Settings


def decode_token(token: str, *, settings: Settings) -> dict[str, Any]:
    """Verify a token's signature/expiry/issuer/audience and return its claims.

    RS256 with the accounts service's public key. Raises `jwt.InvalidTokenError` (or a subclass,
    e.g. `ExpiredSignatureError`) on any failure; the auth dependency maps that to a 401.
    """
    return jwt.decode(
        token,
        settings.public_key,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )
