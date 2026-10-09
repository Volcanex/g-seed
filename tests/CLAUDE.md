# Tests

Smoke-level pytest suite. Each test documents one load-bearing piece of
the framework:

- **Compilation** - `compile.py` runs cleanly; `compile_docs.py` produces
  a valid sentinel block.
- **Server boot** - FastAPI app imports and the built-in health endpoint
  responds.
- **API auto-discovery** - `pages/hello/api.py` is found and mounted at
  `/api/hello/*`.
- **Page serving** - compiled pages in `output/` are served at their
  slug path.
- **Config validity** - every `pages/*/config.json` parses and has a
  title.

## Adding tests

- Framework-level concerns → add here.
- Page-specific tests → colocate at `pages/{slug}/test_{slug}.py` (pytest
  picks them up via rootdir discovery).
- API-specific tests → colocate next to the `api.py`.

Test fixtures live in `conftest.py` (add one if you need session-scoped
DB/client fixtures across colocated tests).
