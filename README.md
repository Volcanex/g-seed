# g-seed

g-seed is the starter template for G-System web apps. Every g- web app is cut from it.

G-System is my agentic development setup. One central server runs the knowledge brain, the alert spine and the dashboard, and other hosts hang off it. Coding agents do much of the work in it, so g-seed keeps its docs where an agent looks first.

This repo is open source under the GNU Affero General Public License v3.0.

## What you get

- **Pages.** Each page is a directory in `pages/` with a `config.json` and a `content.html` fragment. `compile.py` wraps every fragment in one shared shell and writes plain HTML to `output/`.
- **APIs.** Any `api.py` beside a page, or any module in `core/api/`, that exports `router = APIRouter()` is mounted at startup. Nothing is registered by hand.
- **Docs for agents.** Every directory with behaviour that isn't obvious has its own `CLAUDE.md`, with `AGENTS.md` linked to it, and the root `CLAUDE.md` keeps an index of them that `scripts/compile_docs.py` rebuilds.
- **Optional parts.** A single-user admin login, SQLite helpers, a slide-out nav and a pytest suite. Delete any of them and the rest still runs.

## Start an app

```bash
git clone https://github.com/Volcanex/g-seed.git my-app
cd my-app
rm -rf .git && git init
pip install -r requirements.txt

cp .env.example .env
openssl rand -hex 32    # paste into ADMIN_COOKIE_VALUE
set -a && . ./.env && set +a

python3 compile.py      # build pages/ into output/
python3 server.py       # serve on http://127.0.0.1:8080
```

Then rename it before anything else: the title of the README and `CLAUDE.md`, the title in `pages/home/config.json` and the name in `pyproject.toml`. Agents read `CLAUDE.md` first, and an app that still calls itself g-seed sends them the wrong way. Apps record where they came from under `[tool.g-core]` in `pyproject.toml`, which is how the system maps what was cut from what.

The server will not start without `ADMIN_COOKIE_VALUE`. It is the admin session secret, so it has no default. Earlier versions defaulted it to a constant, which let anyone forge the admin cookie. Admin login stays off until `ADMIN_PASSWORD` is set.

## Docker

```bash
cp .env.example .env    # set ADMIN_COOKIE_VALUE, ADMIN_PASSWORD and HOST_PORT
docker compose up -d
```

The app binds to `127.0.0.1:${HOST_PORT}` for a reverse proxy in front of it. `docker compose --profile standalone up -d` adds Caddy with automatic TLS instead. `CLAUDE.md` covers both modes and every optional part.

## Licence

Copyright (C) 2026 Gabriel Penman. Licensed under the GNU Affero General Public License v3.0 only, see `LICENSE`. Versions published before the move away from MIT were released under MIT as seed, and those grants stand (see `NOTICE`).
