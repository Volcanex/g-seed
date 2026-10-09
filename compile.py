#!/usr/bin/env python3
"""
Page compiler - walks `pages/` and writes `output/{slug}.html`.

Each page is a directory under `pages/` with:
- `config.json` - at minimum `{"title": "..."}`. Optional: `description`,
  `slug`, `body_class`, `nav`, `order`, anything else your shell.html
  wants to interpolate.
- `content.html` - HTML fragment for the page body. May include a
  `<style>` block.

The fragment is inserted into `core/templates/shell.html` at the
`{{ content }}` placeholder. `{{ title }}` and any other `{{ key }}`
tokens found in the shell are filled from config.json, falling back to
sensible defaults.

Also copies `core/static/*` into `output/css|js|assets` so the server
can mount them as static.

## Slug-with-slashes

If `config.json` sets a slug like `"admin/audits"`, this compiler writes
`output/admin/audits.html` (parent directories are auto-created). Combined
with the tree-walk fallback in `server.py`, this means a single compiled
HTML can serve every `/<prefix>/<dynamic>` URL - no per-slug page needed.

## Token registry

`<!-- seed:NAME -->` markers in content.html are replaced by registered
renderers before the content is spliced into the shell. Register your
own with `register_token("NAME", lambda ctx: "...")` from a project
hook (most projects don't need this).

## Manifest auto-stub

If `data/manifest.json` exists with shape
`{"items": [{"slug": "...", "title": "..."}]}`, this compiler emits a
default page for every entry that has no hand-written
`pages/{prefix}-{slug}/` directory. Configure via env vars:

  SEED_MANIFEST_PATH       (default: data/manifest.json)
  SEED_MANIFEST_PREFIX     (default: item)        # so item-{slug}.html
  SEED_MANIFEST_TEMPLATE   (default: stub.html)   # under core/templates/

Usage: python3 compile.py
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent
PAGES_DIR = PROJECT_ROOT / "pages"
OUTPUT_DIR = PROJECT_ROOT / "output"
SHELL_PATH = PROJECT_ROOT / "core" / "templates" / "shell.html"
STATIC_SRC = PROJECT_ROOT / "core" / "static"
DATA_DIR = PROJECT_ROOT / "data"
TEMPLATES_DIR = PROJECT_ROOT / "core" / "templates"

DEFAULTS = {
    "title": "Untitled",
    "description": "",
    "site_name": "g-seed",
    "body_class": "",
}

# `{{ key }}` substitutes context[key] HTML-escaped; `{{! key }}` keeps
# the value raw (use this when the value is already-rendered HTML, e.g.
# the page body inside the shell). Escape-by-default keeps user data
# from a manifest/CMS/database from becoming an injection vector.
TOKEN_RE = re.compile(r"\{\{\s*(!?)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

# Slugs become file paths under output/. Allow letters, digits, dash,
# underscore, and forward-slash (for slug-with-slashes). Reject anything
# that could escape the output dir. A bad slug fails the build.
SLUG_RE = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_\-/]*[a-zA-Z0-9_\-]$|^[a-zA-Z0-9_]$")


def _safe_slug(slug: str) -> bool:
    if not isinstance(slug, str) or not slug:
        return False
    if ".." in slug.split("/") or slug.startswith("/") or "\\" in slug:
        return False
    return bool(SLUG_RE.match(slug))


def _safe_output_path(slug: str) -> Path | None:
    """Resolve the output path for a slug and confirm it stays under
    OUTPUT_DIR. Returns None if the slug would escape (defence in depth
    on top of `_safe_slug`)."""
    candidate = (OUTPUT_DIR / f"{slug}.html").resolve()
    try:
        candidate.relative_to(OUTPUT_DIR.resolve())
    except ValueError:
        return None
    return candidate

# Token registry: `<!-- seed:NAME -->` → renderer(context) -> str.
# Projects extend this by importing `register_token` from compile and
# calling it before main() runs (e.g. from a project-level hook).
SEED_TOKEN_RE = re.compile(r"<!--\s*seed:([a-zA-Z0-9_-]+)\s*-->")
_TOKEN_REGISTRY: dict[str, Callable[[dict], str]] = {}


def register_token(name: str, renderer: Callable[[dict], str]) -> None:
    """Register a `<!-- seed:NAME -->` content token. The renderer is
    called once per page and receives the page's render context dict.
    Last registration wins (idempotent override is fine)."""
    _TOKEN_REGISTRY[name] = renderer


def expand_seed_tokens(content: str, context: dict) -> str:
    if not _TOKEN_REGISTRY:
        return content

    def sub(match: re.Match) -> str:
        name = match.group(1)
        renderer = _TOKEN_REGISTRY.get(name)
        if renderer is None:
            return match.group(0)
        try:
            return renderer(context) or ""
        except Exception as exc:  # pragma: no cover - fail loud, keep building
            print(f"  ⚠ token `{name}` raised: {exc}")
            return match.group(0)

    return SEED_TOKEN_RE.sub(sub, content)


def load_shell() -> str:
    if not SHELL_PATH.is_file():
        sys.exit(f"ERROR: shell template not found at {SHELL_PATH}")
    return SHELL_PATH.read_text(encoding="utf-8")


def render(template: str, context: dict) -> str:
    def sub(match: re.Match) -> str:
        raw_marker, key = match.group(1), match.group(2)
        if key not in context:
            return match.group(0)  # unknown key - leave the placeholder
        value = str(context[key])
        return value if raw_marker == "!" else html.escape(value, quote=True)
    return TOKEN_RE.sub(sub, template)


def compile_page(page_dir: Path, shell: str) -> tuple[Path | None, dict | None, bool]:
    """Returns (output_path, config, error). `error=True` means the page
    was malformed (not just missing) - main() exits non-zero so CI catches it."""
    config_file = page_dir / "config.json"
    content_file = page_dir / "content.html"
    if not (config_file.is_file() and content_file.is_file()):
        print(f"  - {page_dir.name}: skipped (missing config.json or content.html)")
        return None, None, False

    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"  ✗ {page_dir.name}: invalid config.json - {exc}")
        return None, None, True

    content = content_file.read_text(encoding="utf-8")
    slug = config.get("slug", page_dir.name)

    if not _safe_slug(slug):
        print(f"  ✗ {page_dir.name}: unsafe slug {slug!r} (letters/digits/-/_/ only)")
        return None, None, True
    out_path = _safe_output_path(slug)
    if out_path is None:
        print(f"  ✗ {page_dir.name}: slug {slug!r} resolves outside output/")
        return None, None, True

    context = {**DEFAULTS, **{k: v for k, v in config.items() if isinstance(v, (str, int, float))}}
    context["slug"] = slug

    # Expand seed:* tokens before splicing into the shell so registered
    # renderers can produce HTML the shell template doesn't know about.
    content = expand_seed_tokens(content, context)
    context["content"] = content

    html = render(shell, context)
    out_path.parent.mkdir(parents=True, exist_ok=True)  # supports slug-with-slashes
    out_path.write_text(html, encoding="utf-8")
    try:
        rel = out_path.relative_to(PROJECT_ROOT)
    except ValueError:
        rel = out_path
    print(f"  ✓ {slug:<28}  →  {rel}")
    return out_path, config, False


def clean_output() -> None:
    """Wipe `output/` before rebuilding so deleted pages don't linger.
    `compile.py` owns this directory entirely - anything you put here
    by hand will be removed on the next build. Use `core/static/` for
    files that should be copied in by `copy_static()`."""
    if not OUTPUT_DIR.is_dir():
        return
    for item in OUTPUT_DIR.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def copy_static() -> int:
    if not STATIC_SRC.is_dir():
        return 0
    count = 0
    for src in STATIC_SRC.rglob("*"):
        if src.is_file():
            rel = src.relative_to(STATIC_SRC)
            dst = OUTPUT_DIR / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            count += 1
    return count


# ---------- Manifest auto-stub --------------------------------------------

# Stub template uses `{key}` placeholders that we substitute one-by-one.
# We deliberately avoid `str.format` so titles/descriptions containing
# `{` or `}` (entirely possible in user data) don't crash the build.
DEFAULT_STUB_BODY = (
    '<article class="seed-stub">'
    '<h1>{title}</h1>'
    '<p>{description}</p>'
    '<p><em>This page was auto-generated from <code>data/manifest.json</code>. '
    'Add a hand-written <code>pages/{prefix}-{slug}/</code> directory to override.</em></p>'
    '</article>'
)


def _fill_stub(template: str, **fields: str) -> str:
    """Substitute `{key}` placeholders. User-supplied fields (title,
    description) are HTML-escaped; structural fields (slug, prefix) are
    already validated by `_safe_slug`, so escape is a harmless no-op."""
    out = template
    for key, value in fields.items():
        out = out.replace("{" + key + "}", html.escape(str(value), quote=True))
    return out


def load_manifest() -> dict:
    path = Path(os.environ.get("SEED_MANIFEST_PATH") or str(DATA_DIR / "manifest.json"))
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def emit_manifest_stubs(shell: str, handled_slugs: set[str]) -> tuple[int, int]:
    """Returns (built, errors). Errors are counted (not raised) so a single
    bad manifest entry doesn't kill the whole build."""
    manifest = load_manifest()
    if not manifest:
        return 0, 0
    items = manifest.get("items") or manifest.get("entries") or []
    if not items:
        return 0, 0

    prefix = os.environ.get("SEED_MANIFEST_PREFIX", "item")
    if not _safe_slug(prefix):
        print(f"  ✗ manifest: unsafe prefix {prefix!r}")
        return 0, 1
    template_name = os.environ.get("SEED_MANIFEST_TEMPLATE", "stub.html")
    template_path = TEMPLATES_DIR / template_name
    template = (
        template_path.read_text(encoding="utf-8")
        if template_path.is_file()
        else DEFAULT_STUB_BODY
    )

    built = 0
    errors = 0
    for item in items:
        slug = item.get("slug")
        if not slug:
            continue
        page_slug = f"{prefix}-{slug}"
        if page_slug in handled_slugs or slug in handled_slugs:
            continue
        if not _safe_slug(page_slug):
            print(f"  ✗ manifest: unsafe slug {slug!r}")
            errors += 1
            continue
        out_path = _safe_output_path(page_slug)
        if out_path is None:
            print(f"  ✗ manifest: slug {slug!r} resolves outside output/")
            errors += 1
            continue
        body = _fill_stub(
            template,
            slug=slug,
            prefix=prefix,
            title=item.get("title", slug),
            description=item.get("description", ""),
        )
        ctx = {
            **DEFAULTS,
            "title": item.get("title", slug),
            "description": item.get("description", ""),
            "slug": page_slug,
            "body_class": "is-stub",
            "content": body,
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render(shell, ctx), encoding="utf-8")
        built += 1
    return built, errors


def main() -> None:
    if not PAGES_DIR.is_dir():
        sys.exit(f"ERROR: {PAGES_DIR} not found")

    OUTPUT_DIR.mkdir(exist_ok=True)
    clean_output()
    shell = load_shell()

    print("Compiling pages...")
    built = 0
    errors = 0
    handled: set[str] = set()
    for page_dir in sorted(PAGES_DIR.iterdir()):
        if not page_dir.is_dir() or page_dir.name.startswith("_"):
            continue
        out, config, err = compile_page(page_dir, shell)
        if out:
            built += 1
        if config:
            handled.add(config.get("slug", page_dir.name))
        if err:
            errors += 1

    stub_built, stub_errors = emit_manifest_stubs(shell, handled)
    errors += stub_errors
    if stub_built:
        print(f"  + {stub_built} stub page(s) auto-emitted from manifest")

    print()
    static_count = copy_static()
    if static_count:
        print(f"Copied {static_count} static file(s) from {STATIC_SRC.relative_to(PROJECT_ROOT)} → output/")
    print(f"Done. {built} page(s) compiled.")
    if errors:
        sys.exit(f"FAILED: {errors} page(s) had errors")


if __name__ == "__main__":
    main()
