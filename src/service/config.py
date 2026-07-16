"""Runtime settings, read from the environment / .env (see .env.example).

Kept free of DB imports so the app and its health check can start without a database.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration. Values come from environment variables (or .env)."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- auth ---
    # DEV_AUTH=1 turns on the local dev-auth stub (fixed identity). MUST be false in any
    # deployed environment; see service.auth and CLAUDE.md.
    dev_auth: bool = False
    # The fixed dev identity used when dev_auth is on (matches the agent's AppContext defaults).
    dev_family_id: str = "16555532-69b5-411e-8526-e0b321fbcfea"
    dev_family_member_id: str = "659c1323-f47a-40eb-a0fe-5fb83f47c9c9"
    dev_child_id: str | None = "d63ae622-797b-4a1c-ae88-9c4309fb3b3a"

    # --- upstream agent ---
    # Base URL of the LangGraph agent server this BFF proxies to.
    agent_url: str = "http://localhost:2024"

    # --- http ---
    # Comma-separated list of allowed CORS origins for the frontend.
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
