"""Smoke tests for the compile.py extensions:

- token registry (`<!-- seed:NAME -->` → renderer)
- slug-with-slashes (`output/admin/foo.html`)
- body_class interpolation
- manifest auto-stub generator

These tests work against the live compile.py without subprocessing -
they import it and call functions directly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _fresh_compile_module():
    """Reload compile so the token registry is empty between tests."""
    for mod_name in list(sys.modules):
        if mod_name == "compile":
            del sys.modules[mod_name]
    import importlib.util
    spec = importlib.util.spec_from_file_location("compile", PROJECT_ROOT / "compile.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_token_registry_expands_seed_tokens():
    mod = _fresh_compile_module()
    mod.register_token("greeting", lambda ctx: f"Hello, {ctx['title']}!")

    out = mod.expand_seed_tokens(
        "<p>before</p><!-- seed:greeting --><p>after</p>",
        {"title": "World"},
    )
    assert out == "<p>before</p>Hello, World!<p>after</p>"


def test_token_registry_leaves_unknown_tokens_alone():
    mod = _fresh_compile_module()
    out = mod.expand_seed_tokens("<!-- seed:unknown -->", {})
    assert out == "<!-- seed:unknown -->"


def test_slug_with_slashes_writes_nested_html(tmp_path, monkeypatch):
    """A slug like 'admin/foo' should write to output/admin/foo.html."""
    mod = _fresh_compile_module()
    monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "output")

    page_dir = tmp_path / "p"
    page_dir.mkdir()
    (page_dir / "config.json").write_text(json.dumps({
        "title": "Foo",
        "slug": "admin/foo",
    }))
    (page_dir / "content.html").write_text("<h1>Foo</h1>")

    shell = "<html><body>{{! content }}</body></html>"
    out, _, err = mod.compile_page(page_dir, shell)
    assert err is False
    assert out is not None
    assert out == tmp_path / "output" / "admin" / "foo.html"
    assert out.is_file()
    assert "<h1>Foo</h1>" in out.read_text()


def test_body_class_token_interpolates_into_shell(tmp_path, monkeypatch):
    mod = _fresh_compile_module()
    monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "output")

    page_dir = tmp_path / "p"
    page_dir.mkdir()
    (page_dir / "config.json").write_text(json.dumps({
        "title": "Cls",
        "body_class": "is-special",
    }))
    (page_dir / "content.html").write_text("body")

    shell = '<html><body class="{{ body_class }}">{{! content }}</body></html>'
    out, _, err = mod.compile_page(page_dir, shell)
    assert err is False
    html_out = out.read_text()
    assert 'class="is-special"' in html_out


def test_manifest_auto_stub_emits_pages_for_unhandled_items(tmp_path, monkeypatch):
    mod = _fresh_compile_module()

    monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "output")

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "items": [
            {"slug": "alpha", "title": "Alpha", "description": "First."},
            {"slug": "beta",  "title": "Beta",  "description": "Second."},
        ]
    }))
    monkeypatch.setenv("SEED_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("SEED_MANIFEST_PREFIX", "thing")

    shell = "<html><body class=\"{{ body_class }}\">{{ content }}</body></html>"
    handled: set[str] = set()  # nothing hand-written
    n, errors = mod.emit_manifest_stubs(shell, handled)

    assert errors == 0
    assert n == 2
    assert (tmp_path / "output" / "thing-alpha.html").is_file()
    assert (tmp_path / "output" / "thing-beta.html").is_file()
    text = (tmp_path / "output" / "thing-alpha.html").read_text()
    assert "Alpha" in text
    assert "is-stub" in text


def test_render_escapes_values_by_default():
    """A title containing HTML must NOT land in the document raw."""
    mod = _fresh_compile_module()
    out = mod.render(
        '<title>{{ title }}</title><meta name="d" content="{{ d }}">',
        {"title": "<script>alert(1)</script>", "d": '"x" onerror="y'},
    )
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
    assert '"x"' not in out  # quote inside attribute is escaped


def test_render_raw_marker_passes_html_through():
    """`{{! key }}` keeps the value raw - used for the page body."""
    mod = _fresh_compile_module()
    out = mod.render("<main>{{! body }}</main>", {"body": "<h1>hi</h1>"})
    assert out == "<main><h1>hi</h1></main>"


def test_render_unknown_keys_left_in_place():
    """Unknown keys still leave the placeholder visible (debug aid)."""
    mod = _fresh_compile_module()
    assert mod.render("{{ unknown }}", {}) == "{{ unknown }}"
    assert mod.render("{{! unknown }}", {}) == "{{! unknown }}"


def test_clean_output_wipes_stale_files_and_dirs(tmp_path, monkeypatch):
    """A page deleted from `pages/` must not survive a recompile."""
    mod = _fresh_compile_module()
    output = tmp_path / "output"
    output.mkdir()
    (output / "old.html").write_text("STALE")
    (output / "css").mkdir()
    (output / "css" / "old.css").write_text("STALE")
    (output / "admin").mkdir()
    (output / "admin" / "audit.html").write_text("STALE")

    monkeypatch.setattr(mod, "OUTPUT_DIR", output)
    mod.clean_output()

    assert output.is_dir()  # directory itself preserved
    assert list(output.iterdir()) == []  # but emptied


def test_unsafe_slug_is_rejected(tmp_path, monkeypatch):
    """A config.json with a traversal-y slug must fail (not silently write
    outside output/)."""
    mod = _fresh_compile_module()
    monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "output")

    page_dir = tmp_path / "p"
    page_dir.mkdir()
    (page_dir / "config.json").write_text(json.dumps({
        "title": "Bad",
        "slug": "../escape",
    }))
    (page_dir / "content.html").write_text("body")

    out, _, err = mod.compile_page(page_dir, "<html>{{ content }}</html>")
    assert out is None
    assert err is True


def test_manifest_stub_with_braces_in_title(tmp_path, monkeypatch):
    """Titles containing `{` used to crash the stub builder via str.format.
    The substitution-based filler keeps them as literal text."""
    mod = _fresh_compile_module()
    monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "output")

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "items": [{"slug": "x", "title": "Pay {0} now", "description": "Use {amount}"}],
    }))
    monkeypatch.setenv("SEED_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("SEED_MANIFEST_PREFIX", "p")

    n, errors = mod.emit_manifest_stubs("<html>{{ content }}</html>", set())
    assert errors == 0
    assert n == 1
    body = (tmp_path / "output" / "p-x.html").read_text()
    assert "Pay {0} now" in body
    assert "Use {amount}" in body


def test_manifest_auto_stub_skips_handled_slugs(tmp_path, monkeypatch):
    mod = _fresh_compile_module()
    monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "output")

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"items": [{"slug": "x", "title": "X"}]}))
    monkeypatch.setenv("SEED_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("SEED_MANIFEST_PREFIX", "p")

    # If the page slug was already handled by a hand-written page, skip it.
    n, errors = mod.emit_manifest_stubs("<html>{{ content }}</html>", {"p-x"})
    assert errors == 0
    assert n == 0
