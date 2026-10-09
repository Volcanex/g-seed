"""Shared test fixtures + env defaults.

Set sane test-time env vars BEFORE any module imports them at load time:

- `ADMIN_PASSWORD`: keeps the admin module's "you forgot to set the
  password" startup warning out of the test output.
- `ADMIN_COOKIE_VALUE`: required; `server.py` refuses to start without
  it. `test_admin.py` covers the refusal in a subprocess.
- `ADMIN_COOKIE_SECURE=0`: TestClient talks to `http://testserver`,
  and `Secure` cookies aren't sent over HTTP, so login/verify round
  trips would fail. Production keeps the default (Secure=True) - see
  `test_admin.py::test_cookie_secure_defaults_to_true`.
"""

from __future__ import annotations

import os

os.environ.setdefault("ADMIN_PASSWORD", "test-pw")
os.environ.setdefault("ADMIN_COOKIE_VALUE", "test-cookie-value-0123456789")
os.environ.setdefault("ADMIN_COOKIE_SECURE", "0")
