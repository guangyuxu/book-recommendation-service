"""Tests for the shared DB infrastructure (engine/session/Base + init_db).

Offline: runs against the in-memory sqlite URL defaulted in conftest. These pin the tooling this
service shares with the agent (Advanced Alchemy + SQLAlchemy) -- the transactional session
boundary, idempotent table creation, the cross-dialect column helpers, and the libpq
`search_path` schema parsing used to scope Postgres tables.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from service.db import (
    Base,
    JSONType,
    SessionLocal,
    TextArray,
    engine,
    init_db,
    session_scope,
)
from service.db.base import _search_path_schema


def test_exports_are_wired() -> None:
    # The package re-exports the infra symbols the rest of the service builds on.
    assert engine is not None
    assert SessionLocal is not None
    assert Base is not None
    assert JSONType is not None
    assert TextArray is not None


def test_init_db_is_idempotent() -> None:
    # No models are registered yet (schema is owned by the agent), so this is a no-op create_all;
    # it must still run cleanly and be safe to call twice.
    init_db()
    init_db()


def test_session_scope_commits_on_success() -> None:
    with session_scope() as session:
        result = session.execute(text("SELECT 1")).scalar_one()
    assert result == 1


def test_session_scope_rolls_back_and_reraises() -> None:
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with session_scope() as session:
            session.execute(text("SELECT 1"))
            raise Boom


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "postgresql+psycopg://u:p@h:5432/db?options=-csearch_path%3Dbook_agent",
            "book_agent",
        ),
        # No options param -> no schema pinned.
        ("postgresql+psycopg://u:p@h:5432/db", None),
        # options present but without a search_path directive.
        ("postgresql+psycopg://u:p@h:5432/db?options=-cstatement_timeout%3D5s", None),
    ],
)
def test_search_path_schema_parsing(url: str, expected: str | None) -> None:
    assert _search_path_schema(url) == expected
