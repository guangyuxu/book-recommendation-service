"""Database infrastructure: engine, session, Base, table creation. Connection via BOOK_AGENT_DATABASE_URL.

Mirrors the agent's DB layer (Advanced Alchemy + SQLAlchemy + psycopg) so this service reads and
writes the SAME Postgres with the SAME tooling. Models are shared with the agent's schema (see
TODO.md for the model-sharing decision); this module owns only the engine/session/Base infra.
"""

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import parse_qs, unquote, urlsplit

from advanced_alchemy.base import AdvancedDeclarativeBase, CommonTableAttributes
from dotenv import load_dotenv
from sqlalchemy import JSON, Text, create_engine, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()  # so standalone scripts (e.g. table creation) can read .env too

# Cross-dialect JSON: JSONB on Postgres (indexable), plain JSON elsewhere (e.g. sqlite).
JSONType = JSON().with_variant(JSONB(), "postgresql")

# Postgres text[] column type; on non-Postgres dialects it degrades to JSON.
TextArray = ARRAY(Text).with_variant(JSON(), "sqlite")

BOOK_AGENT_DATABASE_URL = os.getenv("BOOK_AGENT_DATABASE_URL")
if not BOOK_AGENT_DATABASE_URL:
    raise RuntimeError(
        "BOOK_AGENT_DATABASE_URL is not set; configure it in .env (see .env.example)"
    )

_is_sqlite = BOOK_AGENT_DATABASE_URL.startswith("sqlite")


def _search_path_schema(url: str) -> str | None:
    """Pull the schema out of a libpq `options=-csearch_path=<schema>` query param, if present.

    The URL pins tables to this schema via search_path, but Postgres won't create it for us --
    init_db must create the schema first or CREATE TABLE fails with "no schema has been selected".
    """
    options = parse_qs(urlsplit(url).query).get("options", [None])[0]
    if not options:
        return None
    m = re.search(r"search_path=([^,\s]+)", unquote(options))
    return m.group(1) if m else None


_schema = None if _is_sqlite else _search_path_schema(BOOK_AGENT_DATABASE_URL)
engine = create_engine(
    BOOK_AGENT_DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=not _is_sqlite,  # for Postgres, avoids stale idle connections
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session boundary: commit on success, roll back on error, always close.

    Open one scope per request, build repositories on the yielded session, and let this commit:

        with session_scope() as s:
            FamilyRepository(session=s).get(family_id)
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class Base(CommonTableAttributes, AdvancedDeclarativeBase):
    """Base class for all ORM models.

    Composed from Advanced Alchemy so models share its `orm_registry`/metadata and gain
    `to_dict()`, while staying compatible with the SQLAlchemySyncRepository. Every model declares
    its own `id`/`created_at`/`updated_at` to mirror the live (DB-first) schema exactly.
    """

    __abstract__ = True


def init_db() -> None:
    """Create tables (dev only). In production prefer migrations over create_all."""
    from . import models  # noqa: F401  ensure models are registered on Base.metadata

    if _schema:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{_schema}"'))
    Base.metadata.create_all(engine)
