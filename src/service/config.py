"""Runtime settings, read from the environment / .env (see .env.example).

The BFF is a token VERIFIER only: it holds the RS256 PUBLIC key and verifies tokens issued by the
accounts service; it never signs and never connects to the business DB. Kept free of DB imports so
the app and its health check can start without a database.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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

    # --- token verification (RS256; tokens are ISSUED by the accounts service) ---
    jwt_algorithm: str = "RS256"
    # Verifying key (PEM). Provide inline via JWT_PUBLIC_KEY or a path via JWT_PUBLIC_KEY_PATH.
    # This is the accounts service's PUBLIC key; the BFF never holds a private key.
    jwt_public_key: str | None = None
    jwt_public_key_path: str | None = None
    # Claims contract: the BFF checks that every token's `iss`/`aud` match these before trusting it.
    jwt_issuer: str = "book-recommendation-accounts"
    jwt_audience: str = "book-recommendation"

    # --- upstream agent ---
    # Base URL of the LangGraph agent server this BFF proxies to.
    agent_url: str = "http://localhost:2024"
    # Graph/assistant name registered in the agent's langgraph.json ("agent").
    agent_graph_name: str = "agent"

    # --- accounts service (identity provider + CRUD) ---
    # Base URL of the accounts service. The BFF calls its external face (with the caller's own
    # token) to confirm a client-supplied active child belongs to the caller's family.
    accounts_url: str = "http://localhost:8001"

    # --- http ---
    # Comma-separated list of allowed CORS origins for the frontend.
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def public_key(self) -> str:
        """The RS256 verifying key (PEM). Raises if not configured."""
        if self.jwt_public_key:
            return self.jwt_public_key
        if self.jwt_public_key_path and Path(self.jwt_public_key_path).is_file():
            return Path(self.jwt_public_key_path).read_text(encoding="utf-8")
        raise RuntimeError(
            "no JWT public key configured (set JWT_PUBLIC_KEY or JWT_PUBLIC_KEY_PATH)"
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Fails closed on a missing verifying key: outside dev-auth, the RS256 public key must be
    resolvable, otherwise no token could be verified and identity could not be derived.
    """
    settings = Settings()
    if not settings.dev_auth:
        _ = settings.public_key  # touch it so a missing key fails fast at startup
    return settings
