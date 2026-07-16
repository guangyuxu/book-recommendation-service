"""FastAPI application: the BFF entrypoint.

Wires CORS, health checks, and the identity dependency. Feature routers (chat/stream, HITL
resume, usage, profile CRUD) are added incrementally — see TODO.md for the MVP scope.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import Identity, get_identity
from .config import Settings, get_settings


def create_app() -> FastAPI:
    """Build and configure the FastAPI app."""
    settings = get_settings()
    app = FastAPI(
        title="Book Recommendation Service (BFF)",
        version="0.0.1",
        summary="Pass-through backend for the book-recommendation agent.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        """Liveness probe: the process is up (no dependency checks)."""
        return {"status": "ok"}

    @app.get("/me", tags=["auth"])
    def me(identity: Identity = Depends(get_identity)) -> dict[str, str | None]:
        """Echo the resolved caller identity — useful to verify auth wiring end to end."""
        return identity.to_context()

    return app


app = create_app()


def settings() -> Settings:  # small indirection kept for symmetry / future DI
    """Return the process settings (module-level convenience)."""
    return get_settings()
