"""Create DB tables for local dev (idempotent: existing tables are skipped).

    uv run python scripts/create_tables.py

Uses Base.metadata.create_all under the hood -- it only creates MISSING tables and never drops
or alters existing ones. Dev convenience only; in production prefer migrations. NOTE: this
service shares the agent's schema; until model-sharing is settled (see TODO.md) this creates no
tables of its own -- the agent owns schema creation.
"""

import logging

from dotenv import load_dotenv

load_dotenv()  # pull BOOK_AGENT_DATABASE_URL etc. from .env

from service.db import init_db  # noqa: E402  (import after load_dotenv so the URL is set)

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    logger.info("Tables created (existing tables left untouched).")


if __name__ == "__main__":
    main()
