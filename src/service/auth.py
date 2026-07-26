"""Authentication: resolve the caller's identity, to be injected into the agent run context.

The BFF is the token VERIFIER: it derives identity from an access token ISSUED by the accounts
service (RS256, verified with the accounts service's public key). The seam is pluggable so local
and production share ONE code path: a resolver takes the request and returns an `Identity`; only
the resolver implementation differs.

- Dev (`DEV_AUTH=1`): `_dev_identity` returns a fixed identity (the known dev family/member/child).
  For local use only; disabled in any deployed environment.
- Otherwise: verify the `Bearer <jwt>` (RS256, public key) and derive `family_id` /
  `family_member_id` from the verified claims. Same `Identity` out, same downstream contract.

Identity is ALWAYS derived server-side here; it is never read from client-supplied body/query
params. This service is the authorization gate the agent trusts (see CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, status

from .config import Settings, get_settings
from .security import decode_token


@dataclass(frozen=True)
class Identity:
    """The resolved caller identity, injected into the agent's run context as AppContext."""

    family_id: str
    family_member_id: str
    child_id: str | None = None

    def to_context(self) -> dict[str, str | None]:
        """Shape the identity into the agent's AppContext channel."""
        return {
            "family_id": self.family_id,
            "family_member_id": self.family_member_id,
            "child_id": self.child_id,
        }


def _dev_identity(settings: Settings) -> Identity:
    return Identity(
        family_id=settings.dev_family_id,
        family_member_id=settings.dev_family_member_id,
        child_id=settings.dev_child_id,
    )


async def get_identity(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Identity:
    """Resolve the caller identity for this request (FastAPI dependency).

    Dev mode returns the fixed dev identity. Otherwise a real token verifier must run; until it is
    implemented we fail closed with 401 rather than trusting anything from the client.
    """
    if settings.dev_auth:
        return _dev_identity(settings)

    return _identity_from_bearer(authorization, settings)


def _identity_from_bearer(authorization: str | None, settings: Settings) -> Identity:
    """Verify a `Bearer <jwt>` header (RS256) and derive identity from the token's claims.

    `family_id` / `family_member_id` come ONLY from the verified token — never from the client's
    body or query — so this remains the authorization gate the agent trusts (see CLAUDE.md).
    `child_id` is not carried in the token; the active child is selected and validated per request.
    """
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_token(token, settings=settings)
        return Identity(
            family_id=str(claims["family_id"]),
            family_member_id=str(claims["family_member_id"]),
        )
    except (jwt.InvalidTokenError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
