#!/usr/bin/env python3
"""
g-seed framework - FastAPI with page+router auto-discovery.

Two conventions drive the server:

1. Pages live at `pages/{slug}/content.html` + `pages/{slug}/config.json`.
   `compile.py` walks these and emits `output/{slug}.html` wrapped in
   `core/templates/shell.html`. The server serves `output/` as static.

2. API routers live at `pages/{slug}/api.py` (or `core/api/*.py`, or any
   `*/api/*.py`). Each file must export `router = APIRouter()`. Discovery
   scans the tree at startup and mounts each router at a path derived from
   its file location. No manual registration.
"""

import hmac
import importlib.util
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# Admin auth (cookie-based, single-user). Configurable via env vars so
# downstream projects can rename the cookie without forking server.py.
# The matching login/logout/verify endpoints live in core/api/admin.py.
#
# ADMIN_COOKIE_VALUE has no default. Whoever presents it is admin, so a
# constant default (earlier versions shipped "ok") lets anyone forge
# the cookie. Refuse to start instead of falling back to one.
ADMIN_COOKIE = os.environ.get("ADMIN_COOKIE", "seed_admin")
ADMIN_VALUE = os.environ.get("ADMIN_COOKIE_VALUE", "").strip()
ADMIN_VALUE_MIN_LENGTH = 16

if len(ADMIN_VALUE) < ADMIN_VALUE_MIN_LENGTH:
    sys.exit(
        "Refusing to start: ADMIN_COOKIE_VALUE is unset or shorter than "
        f"{ADMIN_VALUE_MIN_LENGTH} characters.\n"
        "It is the admin session secret: any request carrying it is "
        "treated as admin. Generate one with\n"
        "  python3 -c 'import secrets; print(secrets.token_urlsafe(32))'\n"
        "and set it in the environment (see .env.example)."
    )


def _is_admin(request: Request) -> bool:
    cookie = request.cookies.get(ADMIN_COOKIE)
    return cookie is not None and hmac.compare_digest(cookie.encode(), ADMIN_VALUE.encode())


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"
_OUTPUT_RESOLVED = OUTPUT_DIR.resolve()

_discovered: list[dict] = []
# Every route mounted from a discovered router, recorded at mount time.
# FastAPI 0.138+ keeps an included router as one private entry in
# app.routes instead of copying its routes in, so /api/_routes can't
# rely on app.routes alone.
_mounted_routes: list[tuple[str, set[str]]] = []


def _safe_under_output(candidate: Path) -> Path | None:
    """Resolve `candidate` and confirm it stays under OUTPUT_DIR.
    Defends the catch-all serve_pages route against `..` traversal in
    the URL path (Starlette doesn't normalise these for us)."""
    try:
        resolved = candidate.resolve()
        resolved.relative_to(_OUTPUT_RESOLVED)
    except (ValueError, OSError):
        return None
    return resolved if resolved.is_file() else None


def _mount_router(app: FastAPI, py_file: Path, prefix: str, group: str) -> None:
    module_name = f"{group}.{py_file.stem}".replace("/", ".")
    spec = importlib.util.spec_from_file_location(module_name, py_file)
    if spec is None or spec.loader is None:
        print(f"  ✗ {py_file.relative_to(PROJECT_ROOT)}: could not load")
        return

    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec - Pydantic v2 (and any forward
    # references) need the module reachable by its qualified name to
    # rebuild model schemas. Without this you get
    # "TypeAdapter[X] is not fully defined" at request time as soon as
    # an endpoint declares a body model. Don't revert.
    sys.modules[module_name] = module
    parent = str(py_file.parent.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        print(f"  ✗ {py_file.relative_to(PROJECT_ROOT)}: {exc}")
        return

    router = getattr(module, "router", None)
    if router is None:
        print(f"  ⚠ {py_file.relative_to(PROJECT_ROOT)}: no `router` exported")
        return

    app.include_router(router, prefix=prefix)
    for route in router.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            _mounted_routes.append((prefix + route.path, set(route.methods)))
    _discovered.append({"file": str(py_file.relative_to(PROJECT_ROOT)), "prefix": prefix})
    print(f"  ✓ {prefix}  ←  {py_file.relative_to(PROJECT_ROOT)}")


def discover_apis(app: FastAPI) -> None:
    """
    Mount all API routers found in the repo.

    Conventions (in order):
    - `core/api/{name}.py`       → `/api/{name}`
    - `pages/{slug}/api.py`      → `/api/{slug}`
    - `{anything}/api/{name}.py` → `/api/{anything}/{name}`

    `{anything}` in the third form is the directory name - this is the
    "core/product split" escape hatch. One top-level product by default
    (`pages/`); add more top-level dirs only when you truly need isolation.
    """
    # core/api/*.py → /api/*
    core_api = PROJECT_ROOT / "core" / "api"
    if core_api.is_dir():
        for py in sorted(core_api.glob("*.py")):
            if py.name.startswith("_"):
                continue
            _mount_router(app, py, f"/api/{py.stem}", "core.api")

    # pages/{slug}/api.py → /api/{slug}
    pages_dir = PROJECT_ROOT / "pages"
    if pages_dir.is_dir():
        for api_py in sorted(pages_dir.glob("*/api.py")):
            slug = api_py.parent.name
            _mount_router(app, api_py, f"/api/{slug}", f"pages.{slug}")

    # Any other top-level */api/*.py → /api/{top}/{name}
    # Skip rules: dot-prefixed dirs, common cache/build dirs, and the
    # framework dirs already handled above. New top-level dirs (data/,
    # node_modules/, etc.) are skipped automatically by the dot/cache
    # rule or by the "no api/ subdir" check below - no blocklist edits
    # needed when you add one.
    _framework_dirs = {"core", "pages", "output", "tests", "scripts", "static"}
    _cache_dirs = {"__pycache__", "venv", ".venv", "node_modules", "dist", "build"}
    for top in sorted(PROJECT_ROOT.iterdir()):
        if not top.is_dir():
            continue
        if top.name.startswith(".") or top.name in _framework_dirs or top.name in _cache_dirs:
            continue
        api_dir = top / "api"
        if not api_dir.is_dir():
            continue
        for py in sorted(api_dir.glob("*.py")):
            if py.name.startswith("_"):
                continue
            _mount_router(app, py, f"/api/{top.name}/{py.stem}", f"{top.name}.api")


app = FastAPI(
    title="g-seed",
    description="Static-first site framework with FastAPI routers.",
    version="2.0.0",
)


print("Discovering APIs...")
discover_apis(app)
print()


@app.get("/api/_health", tags=["system"])
async def health():
    return {"status": "ok"}


@app.get("/api/_routes", tags=["system"])
async def routes():
    """List discovered routers and all mounted routes. Handy for sanity checks."""
    by_path: dict[str, set[str]] = {}
    app_routes = [
        (route.path, route.methods)
        for route in app.routes
        if hasattr(route, "methods") and hasattr(route, "path")
    ]
    # Older FastAPI also lists the mounted routes in app.routes, so merge
    # by path rather than appending.
    for path, methods in _mounted_routes + app_routes:
        if path.startswith("/api/"):
            by_path.setdefault(path, set()).update(methods)
    all_routes = [
        {"path": path, "methods": sorted(m for m in methods if m not in {"HEAD", "OPTIONS"})}
        for path, methods in sorted(by_path.items())
    ]
    return {"discovered": _discovered, "routes": all_routes}


# Static assets compiled by compile.py (CSS, JS, images)
if OUTPUT_DIR.exists():
    for sub in ("css", "js", "assets"):
        p = OUTPUT_DIR / sub
        if p.is_dir():
            app.mount(f"/{sub}", StaticFiles(directory=p), name=sub)


def _admin_gated(path: str, request: Request) -> "RedirectResponse | None":
    """Return a redirect-to-login response if path is admin-only and the
    visitor isn't authenticated. None means: pass through.

    Generic gate: any path under `/admin` (except `/admin/login`) requires
    the admin cookie. Configure cookie + redirect via env vars at the top
    of this file. The matching auth endpoints live in core/api/admin.py.
    """
    parts = path.strip("/").split("/")
    if not parts or parts[0] != "admin":
        return None
    # Login page itself is public
    if len(parts) >= 2 and parts[1] == "login":
        return None
    if _is_admin(request):
        return None
    return RedirectResponse(url="/admin/login", status_code=302)


@app.get("/{path:path}", include_in_schema=False)
async def serve_pages(path: str, request: Request):
    """Serve compiled HTML pages with clean URLs."""
    if path.startswith("api/"):
        return JSONResponse({"error": "not found"}, status_code=404)

    # Admin auth gate - only fires if the project has an /admin/* page.
    redirect = _admin_gated(path, request)
    if redirect is not None:
        return redirect

    if path in ("", "/"):
        index = OUTPUT_DIR / "home.html"
        if index.is_file():
            return FileResponse(index)
        return HTMLResponse(_placeholder_home(), status_code=200)

    # Direct file match
    if (resolved := _safe_under_output(OUTPUT_DIR / path)) is not None:
        return FileResponse(resolved)

    # Slug → output/{slug}.html
    if (resolved := _safe_under_output(OUTPUT_DIR / f"{path}.html")) is not None:
        return FileResponse(resolved)

    # Directory index
    if (resolved := _safe_under_output(OUTPUT_DIR / path / "index.html")) is not None:
        return FileResponse(resolved)

    # Tree-walk fallback for dynamic URLs:
    #   /report/{any-slug}        → output/report.html
    #   /admin/audit/{any-slug}   → output/admin/audit.html
    # The first matching prefix wins. Lets one compiled HTML file handle
    # every variant of /report/X without per-slug compilation. The page
    # reads the slug from `location.pathname` and fetches via its API.
    parts = path.strip("/").split("/")
    for i in range(len(parts) - 1, 0, -1):
        candidate = OUTPUT_DIR / ("/".join(parts[:i]) + ".html")
        if (resolved := _safe_under_output(candidate)) is not None:
            return FileResponse(resolved)

    return HTMLResponse(_placeholder_404(path), status_code=404)


def _placeholder_home() -> str:
    return (
        "<!doctype html><title>g-seed</title>"
        "<h1>g-seed is running, but nothing is compiled yet.</h1>"
        "<p>Run <code>python3 compile.py</code> to build pages.</p>"
    )


def _placeholder_404(path: str) -> str:
    from html import escape
    return (
        "<!doctype html><title>Not found</title>"
        f"<h1>404</h1><p><code>/{escape(path)}</code> does not exist.</p>"
        "<p><a href=\"/\">Home</a></p>"
    )


if __name__ == "__main__":
    # Default to loopback so a stray `python3 server.py` on a laptop
    # doesn't expose the app on the LAN. Containers set HOST=0.0.0.0 in
    # the Dockerfile so the compose port-forward keeps working.
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    reload_flag = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")
    uvicorn.run("server:app", host=host, port=port, reload=reload_flag)
