"""Make unit tests hermetic: default the DB URL to in-memory sqlite before any import.

`service.db.base` raises at import time when BOOK_AGENT_DATABASE_URL is unset and builds its
engine from it. Most unit tests never touch the DB, but importing `service.*` transitively can,
so we default the var. `setdefault` means a URL already exported (e.g. CI's Postgres) still wins.
"""

import os

os.environ.setdefault("BOOK_AGENT_DATABASE_URL", "sqlite:///:memory:")
