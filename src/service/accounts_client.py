"""Async client for the accounts service (identity provider + family/child CRUD).

The BFF no longer touches the business DB. To enforce that a client-supplied active `child_id`
belongs to the caller's family, it asks the accounts service — using the caller's OWN bearer token,
so accounts applies its family-scoped `get_in_family` guard and the BFF never needs DB access or a
service credential for this read.

Exposed as the FastAPI dependency `get_accounts_client`; tests override it with a fake.
"""

from __future__ import annotations

from functools import lru_cache

import httpx

from .config import get_settings


class AccountsClient:
    """Minimal async facade over the accounts service's external face."""

    def __init__(self, *, url: str) -> None:
        self._url = url.rstrip("/")

    async def child_belongs_to_family(
        self, child_id: str, *, bearer_token: str
    ) -> bool:
        """Return True iff the child exists and belongs to the caller's family.

        Accounts enforces the family scope from the token, so a 200 means "owned"; anything else
        (404 not-found/foreign, 422 malformed id, 401 bad token) means "not owned".
        """
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{self._url}/family/children/{child_id}",
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
        return resp.status_code == 200

    async def healthz(self) -> bool:
        """Readiness ping for the accounts service (never raises)."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self._url}/healthz")
            return resp.status_code == 200
        except Exception:  # noqa: BLE001 — readiness must never raise
            return False


@lru_cache
def get_accounts_client() -> AccountsClient:
    """Return the process-wide accounts client (FastAPI dependency; overridden in tests)."""
    return AccountsClient(url=get_settings().accounts_url)
