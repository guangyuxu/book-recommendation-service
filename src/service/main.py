"""FastAPI application: the BFF entrypoint.

Wires logging, the correlation-id middleware, CORS, health/readiness probes, a uniform error
envelope, and the chat proxy router. Identity is resolved by the `service.auth` dependency (token
verified with the accounts service's public key) and injected into the agent run context
downstream. The BFF holds no DB connection — auth and CRUD live in the accounts service.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .accounts_client import get_accounts_client
from .auth import Identity, get_identity
from .config import get_settings
from .logging import configure_logging, request_id_var
from .middleware import CorrelationIdMiddleware
from .routers import chat

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or request_id_var.get()


def _envelope(request: Request, status_code: int, message: Any) -> JSONResponse:
    """Uniform error envelope carrying the correlation id."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": status_code,
                "message": message,
                "request_id": _request_id(request),
            }
        },
    )


def create_app() -> FastAPI:
    """Build and configure the FastAPI app."""
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title="Book Recommendation Service (BFF)",
        version="0.0.1",
        summary="Pass-through backend for the book-recommendation agent.",
    )

    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException) -> JSONResponse:
        return _envelope(request, exc.status_code, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _envelope(request, 422, exc.errors())

    @app.exception_handler(Exception)
    async def _unhandled_exc(request: Request, exc: Exception) -> JSONResponse:
        # PII-safe: log only the exception type, never its message/args.
        logger.exception("unhandled error: %s", type(exc).__name__)
        return _envelope(request, 500, "internal server error")

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        """Liveness probe: the process is up (no dependency checks)."""
        return {"status": "ok"}

    @app.get("/me", tags=["auth"])
    async def me(identity: Identity = Depends(get_identity)) -> dict[str, str | None]:
        """Echo the resolved caller identity — verifies the token-verification seam end to end."""
        return identity.to_context()

    @app.get("/readyz", tags=["health"])
    async def readyz() -> JSONResponse:
        """Readiness probe: verify the upstream agent and the accounts service are reachable.

        The BFF holds no DB connection, so there is nothing DB-shaped to check here.
        """
        agent_ok = await _check_agent(settings.agent_url)
        accounts_ok = await get_accounts_client().healthz()
        ready = agent_ok and accounts_ok
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ok" if ready else "degraded",
                "checks": {"agent": agent_ok, "accounts": accounts_ok},
            },
        )

    app.include_router(chat.router)
    return app


async def _check_agent(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{url.rstrip('/')}/ok")
        return resp.status_code == 200
    except Exception as exc:  # noqa: BLE001 — readiness must never raise
        logger.warning("agent readiness check failed: %s", type(exc).__name__)
        return False


app = create_app()
