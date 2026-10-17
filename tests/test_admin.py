"""Smoke tests for the admin auth extraction.

Covers: cookie set on correct password, gate redirect, verify endpoint,
helper exports, and the refusal to start without a cookie secret.
Doesn't cover the test runner endpoint (which would shell out to pytest
itself).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module", autouse=True)
def compile_pages():
    result = subprocess.run(
        [sys.executable, "compile.py"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"compile.py failed:\n{result.stderr}"


@pytest.fixture(scope="module")
def client():
    os.environ["ADMIN_PASSWORD"] = "test-pw"
    sys.path.insert(0, str(PROJECT_ROOT))
    from server import app  # noqa: E402
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Each test starts with a clean per-IP login bucket. Otherwise the
    rate-limit-exhaustion test would poison everything that runs after."""
    import sys as _sys
    admin_mod = _sys.modules.get("core.api.admin")
    if admin_mod is not None:
        admin_mod._LOGIN_ATTEMPTS.clear()
    yield
    if admin_mod is not None:
        admin_mod._LOGIN_ATTEMPTS.clear()


def test_admin_endpoints_mounted(client):
    """The admin module must auto-discover and expose its endpoints."""
    r = client.get("/api/_routes")
    assert r.status_code == 200
    paths = {route["path"] for route in r.json()["routes"]}
    assert "/api/admin/login" in paths
    assert "/api/admin/logout" in paths
    assert "/api/admin/verify" in paths


def test_verify_default_is_logged_out(client):
    r = client.get("/api/admin/verify")
    assert r.status_code == 200
    assert r.json() == {"admin": False}


def test_login_wrong_password_rejected(client):
    r = client.post("/api/admin/login", json={"password": "wrong"})
    assert r.status_code == 401


def test_login_sets_cookie_and_verify_flips(client):
    r = client.post("/api/admin/login", json={"password": "test-pw"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    r2 = client.get("/api/admin/verify")
    assert r2.json() == {"admin": True}

    # Logout clears it
    r3 = client.post("/api/admin/logout")
    assert r3.status_code == 200
    r4 = client.get("/api/admin/verify")
    assert r4.json() == {"admin": False}


def test_admin_path_redirects_when_logged_out(client):
    """Hitting any /admin/* path without the cookie should 302 to login.
    The login page itself is exempt."""
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/admin/login"

    r2 = client.get("/admin/dashboard", follow_redirects=False)
    assert r2.status_code == 302


def test_admin_login_path_is_public(client):
    """The /admin/login page must NOT redirect (otherwise infinite loop)."""
    # Compiled output has no /admin/login page in the bare seed, so we
    # expect a 404 - but crucially NOT a 302 redirect to itself.
    r = client.get("/admin/login", follow_redirects=False)
    assert r.status_code != 302


def test_login_rate_limit_kicks_in_after_threshold(client):
    """5 failed attempts → 401; the 6th → 429. Even a correct password
    after the threshold is blocked until the window expires."""
    for _ in range(5):
        r = client.post("/api/admin/login", json={"password": "wrong"})
        assert r.status_code == 401
    r6 = client.post("/api/admin/login", json={"password": "wrong"})
    assert r6.status_code == 429
    r7 = client.post("/api/admin/login", json={"password": "test-pw"})
    assert r7.status_code == 429


def test_successful_login_clears_rate_limit(client):
    """Legit usage isn't penalised - a successful login resets the bucket."""
    for _ in range(4):
        r = client.post("/api/admin/login", json={"password": "wrong"})
        assert r.status_code == 401
    ok = client.post("/api/admin/login", json={"password": "test-pw"})
    assert ok.status_code == 200
    # Bucket now empty - five more failures should still be 401, not 429
    for _ in range(5):
        r = client.post("/api/admin/login", json={"password": "wrong"})
        assert r.status_code == 401


def test_rate_limit_keys_on_real_ip_not_forwarded_for(client):
    """The limiter must key on nginx's X-Real-IP, not the client-supplied
    X-Forwarded-For. A client that rotates X-Forwarded-For on every request
    (nginx appends to that header rather than replacing it, so its first
    entry is attacker-controlled) must still be rate-limited, because the
    real peer address is the same every time."""
    real_ip = {"X-Real-IP": "203.0.113.9"}
    for i in range(5):
        r = client.post(
            "/api/admin/login",
            json={"password": "wrong"},
            headers={**real_ip, "X-Forwarded-For": f"10.0.0.{i}"},
        )
        assert r.status_code == 401
    r6 = client.post(
        "/api/admin/login",
        json={"password": "wrong"},
        headers={**real_ip, "X-Forwarded-For": "10.0.0.250"},
    )
    assert r6.status_code == 429, (
        "limiter was dodged by rotating X-Forwarded-For - it must key on "
        "X-Real-IP, not the client-supplied forwarding header"
    )


def test_client_ip_uses_real_ip_and_ignores_forwarded_for():
    """_client_ip reads X-Real-IP and ignores X-Forwarded-For entirely."""
    import sys as _sys

    from starlette.datastructures import Headers

    admin_mod = _sys.modules.get("core.api.admin")
    assert admin_mod is not None

    class _Req:
        def __init__(self, headers):
            self.headers = Headers(headers)
            self.client = None

    assert (
        admin_mod._client_ip(
            _Req({"x-real-ip": "198.51.100.7", "x-forwarded-for": "1.2.3.4"})
        )
        == "198.51.100.7"
    )


def test_cookie_secure_defaults_to_true(monkeypatch):
    """Production default: cookie carries the Secure flag. Conftest only
    drops it for the TestClient because TestClient uses http://."""
    monkeypatch.delenv("ADMIN_COOKIE_SECURE", raising=False)
    import sys as _sys
    admin_mod = _sys.modules.get("core.api.admin")
    assert admin_mod is not None
    assert admin_mod._admin_cookie_secure() is True


def test_cookie_secure_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ADMIN_COOKIE_SECURE", "0")
    import sys as _sys
    admin_mod = _sys.modules.get("core.api.admin")
    assert admin_mod._admin_cookie_secure() is False


def test_forged_cookie_is_not_admin(client):
    """A cookie with the right name but a guessed value (the old constant
    default "ok", say) must not pass the gate or the verify endpoint."""
    client.cookies.set("seed_admin", "ok")
    try:
        assert client.get("/api/admin/verify").json() == {"admin": False}
        r = client.get("/admin/dashboard", follow_redirects=False)
        assert r.status_code == 302
    finally:
        client.cookies.clear()


@pytest.mark.parametrize("value", [None, "", "ok", "too-short-value"])
def test_server_refuses_to_start_without_cookie_secret(value):
    """No constant default: an unset, empty or short ADMIN_COOKIE_VALUE
    stops the app at import with a message naming the variable."""
    env = {k: v for k, v in os.environ.items() if k != "ADMIN_COOKIE_VALUE"}
    if value is not None:
        env["ADMIN_COOKIE_VALUE"] = value
    result = subprocess.run(
        [sys.executable, "-c", "import server"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "ADMIN_COOKIE_VALUE" in result.stderr
    assert "Discovering APIs" not in result.stdout


@pytest.mark.parametrize("password", [None, "change-me"])
def test_login_disabled_until_password_set(client, monkeypatch, password):
    """An unset or placeholder ADMIN_PASSWORD must not be a working
    password: login answers 503 and sets no cookie."""
    if password is None:
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("ADMIN_PASSWORD", password)
    r = client.post("/api/admin/login", json={"password": "change-me"})
    assert r.status_code == 503
    assert client.get("/api/admin/verify").json() == {"admin": False}
