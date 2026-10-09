"""Smoke tests - verify the core framework wires up.

Run: `pytest` from repo root.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def compile_pages():
    """Compile pages once for the whole test session."""
    result = subprocess.run(
        [sys.executable, "compile.py"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"compile.py failed:\n{result.stderr}"


@pytest.fixture(scope="session")
def client():
    """Import the app after compilation and return a TestClient."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from server import app  # noqa: E402
    return TestClient(app)


def test_health(client):
    r = client.get("/api/_health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_routes_index_lists_hello(client):
    r = client.get("/api/_routes")
    assert r.status_code == 200
    body = r.json()
    paths = [route["path"] for route in body["routes"]]
    assert "/api/hello/" in paths
    assert "/api/hello/echo" in paths


def test_hello_api(client):
    r = client.get("/api/hello/")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_hello_echo(client):
    r = client.get("/api/hello/echo", params={"msg": "seed"})
    assert r.status_code == 200
    assert r.json() == {"echo": "seed"}


def test_home_page_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert "<title>Home" in body
    assert "Pages" in body  # grid card content


def test_hello_page_renders(client):
    r = client.get("/hello")
    assert r.status_code == 200
    assert "Hello" in r.text


def test_404_on_missing_page(client):
    r = client.get("/definitely-not-a-page")
    assert r.status_code == 404


def test_compile_docs_runs_cleanly():
    """The docs compiler must run without errors against a fresh repo."""
    result = subprocess.run(
        [sys.executable, "scripts/compile_docs.py"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"compile_docs.py failed:\n{result.stderr}"

    # Root CLAUDE.md should have an index block
    root = (PROJECT_ROOT / "CLAUDE.md").read_text()
    assert "<!-- DOCS:START -->" in root
    assert "<!-- DOCS:END -->" in root


def test_home_config_is_valid_json():
    """Every pages/*/config.json must parse as JSON with a title."""
    for cfg in (PROJECT_ROOT / "pages").glob("*/config.json"):
        data = json.loads(cfg.read_text())
        assert "title" in data, f"{cfg} missing title"
