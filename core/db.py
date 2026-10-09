"""SQLite scaffolding - connection helper, idempotent init, and a place
to put your schema.

This file is intentionally tiny. It gives you:

- A `DB_PATH` that env-var-overrides for tests / alternate deployments.
- A `SCHEMA` string containing the project's tables (CREATE TABLE IF
  NOT EXISTS so it's safe to run on every import).
- `init_db()` - idempotent.
- `get_conn()` - context-managed connection with `Row` factory and
  auto-commit/rollback semantics.

The example schema below is a single `kv` table - replace it with your
own. For larger projects, switch `SCHEMA` to a list of migration files
loaded from a `core/migrations/` directory.

When you outgrow SQLite (concurrent writers, real users, > ~10k rows of
hot data), swap to Postgres: change the connection function, keep the
context-manager surface. The SQL is usually portable enough that schema
+ queries don't change.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Override via env var for tests and alternate deployments.
DB_PATH = Path(
    os.environ.get("SEED_DB_PATH") or str(PROJECT_ROOT / "data" / "seed.db")
)

# Replace this with your project's schema. The example `kv` table exists
# only so the smoke test has something to read/write - there's no
# expectation downstream projects keep it.
SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS kv (
  key         TEXT PRIMARY KEY,
  value       TEXT NOT NULL,
  updated_at  TEXT DEFAULT (datetime('now'))
);
"""


def init_db() -> None:
    """Idempotent. Safe to call on every import."""
    DB_PATH.parent.mkdir(exist_ok=True, parents=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_conn():
    """Context-managed connection.

    - Auto-commits on clean exit; rolls back on exception.
    - `row_factory = sqlite3.Row` so rows behave like dicts.
    - Foreign keys are enforced per connection.

    Usage:

        from core.db import get_conn

        with get_conn() as conn:
            row = conn.execute("SELECT * FROM kv WHERE key = ?", (k,)).fetchone()
            conn.execute("INSERT INTO kv(key, value) VALUES(?, ?)", (k, v))
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Initialise schema on import.
init_db()
