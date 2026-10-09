# Templates - the shared shell

`shell.html` is the outer HTML every page is wrapped in. `compile.py`
replaces `{{ content }}` with each page's `content.html` fragment and
interpolates other `{{ key }}` tokens from the page's `config.json`
(falling back to defaults in `compile.py`).

## Tokens available by default

- `{{ title }}` - from page config, default `"Untitled"`
- `{{ description }}` - from page config, default `""`
- `{{ site_name }}` - default `"g-seed"` (override in `compile.py` DEFAULTS)
- `{{ slug }}` - always set, equal to `config.slug` or the directory name
- `{{ content }}` - the page body fragment
- Any other string/number field in `config.json` (e.g. `{{ author }}`)

## Adding a nav link

The default shell's `<nav>` hand-lists links. For a data-driven nav,
extend `compile.py` to assemble a nav fragment from all pages' configs
(where `nav: true`) and expose it as a token. This is intentionally not
built-in - start simple; add when you have a real need.

## Styling

`core/static/css/base.css` is copied to `output/css/base.css` at compile
time, alongside `nav.css` and `admin.css`. Page-specific styles go in
that page's `content.html` inside a `<style>` block.

## body_class

`shell.html` interpolates `{{ body_class }}` on `<body>`. Set
`"body_class": "is-something"` in a page's `config.json` to scope
overrides without polluting global stylesheets. Useful for the login
page (`is-admin-login`), wide admin pages (`is-admin-page`), and any
page-shape-changes that don't deserve their own template.
