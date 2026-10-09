"""Smoke tests for the SQLite scaffolding (core/db.py).

Covers: env-var override, idempotent init, get_conn round-trip, rollback
on exception. Uses a tmp DB so no live state is touched.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Point core.db at a fresh temp file per test."""
    db_file = tmp_path / "smoke.db"
    monkeypatch.setenv("SEED_DB_PATH", str(db_file))
    # Force module reload so DB_PATH picks up the env var
    for mod_name in list(sys.modules):
        if mod_name == "core.db" or mod_name.endswith(".core.db"):
            del sys.modules[mod_name]
    import importlib
    import importlib.util
    spec = importlib.util.spec_from_file_location("core.db", PROJECT_ROOT / "core" / "db.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_init_creates_db_and_kv_table(tmp_db):
    assert tmp_db.DB_PATH.is_file()
    with tmp_db.get_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='kv'"
        ).fetchall()
    assert len(rows) == 1


def test_get_conn_round_trip(tmp_db):
    with tmp_db.get_conn() as conn:
        conn.execute("INSERT INTO kv(key, value) VALUES (?, ?)", ("hello", "world"))

    with tmp_db.get_conn() as conn:
        row = conn.execute("SELECT value FROM kv WHERE key=?", ("hello",)).fetchone()

    assert row is not None
    assert row["value"] == "world"


def test_get_conn_rolls_back_on_exception(tmp_db):
    """Mid-transaction exception → no partial write committed."""
    with pytest.raises(RuntimeError):
        with tmp_db.get_conn() as conn:
            conn.execute("INSERT INTO kv(key, value) VALUES (?, ?)", ("k", "v"))
            raise RuntimeError("boom")

    with tmp_db.get_conn() as conn:
        row = conn.execute("SELECT value FROM kv WHERE key=?", ("k",)).fetchone()
    assert row is None


def test_init_is_idempotent(tmp_db):
    tmp_db.init_db()
    tmp_db.init_db()
    # No exception, table still there
    with tmp_db.get_conn() as conn:
        conn.execute("INSERT INTO kv(key, value) VALUES (?, ?)", ("a", "b"))
