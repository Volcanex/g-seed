#!/bin/sh
# Container entrypoint: compile pages, then start the server.
#
# Compile runs at *container start* (not just image build) so that when
# pages/ is volume-mounted in dev, edits are reflected without a rebuild.
set -eu

cd /app
python3 compile.py
exec python3 server.py
