"""Smoke test for the tree-walk fallback in server.py.

When the URL has more path segments than any compiled HTML file, the
catch-all serves the longest-matching prefix's HTML. This lets one
file handle every variant of `/<prefix>/<dynamic>` - the page reads
the slug from `location.pathname` and fetches via its API.
"""

from __future__ import annotations

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
    assert result.returncode == 0


@pytest.fixture(scope="module")
def client():
    sys.path.insert(0, str(PROJECT_ROOT))
    from server import app  # noqa: E402
    return TestClient(app)


def test_tree_walk_serves_prefix_html_for_dynamic_subpaths(tmp_path, client):
    """Manually drop a `report.html` into output/ and confirm the catch-all
    serves it for `/report/anything`."""
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(exist_ok=True)
    report_html = output_dir / "report.html"
    report_html.write_text("<html><body>REPORT_PAGE</body></html>", encoding="utf-8")

    try:
        # Direct match still works
        r1 = client.get("/report")
        assert r1.status_code == 200
        assert "REPORT_PAGE" in r1.text

        # Tree-walk: /report/anything-here also serves the same file
        r2 = client.get("/report/some-slug")
        assert r2.status_code == 200
        assert "REPORT_PAGE" in r2.text

        # Two layers deep: /report/a/b also matches the report prefix
        r3 = client.get("/report/a/b")
        assert r3.status_code == 200
        assert "REPORT_PAGE" in r3.text
    finally:
        report_html.unlink(missing_ok=True)


def test_tree_walk_404s_when_no_prefix_matches(client):
    r = client.get("/no-such-thing/sub/path")
    assert r.status_code == 404


def test_path_traversal_attempt_404s(client):
    """`..` segments must not escape output/ - the resolve-and-confine
    check in server.py rejects them."""
    # TestClient normalises some forms, so try a few flavours that can
    # reach the catch-all. Each must 404, never 200 with file contents.
    for victim_path in ("../server.py", "..%2fserver.py", "../../etc/passwd"):
        r = client.get(f"/{victim_path}")
        assert r.status_code == 404, f"{victim_path!r} did not 404 (got {r.status_code})"
