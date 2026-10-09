FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    HOST=0.0.0.0

WORKDIR /app

# Install deps first so this layer caches across source edits.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Run as a non-root user. UID 1000 typically matches the host dev user,
# which keeps volume-mounted file ownership sane.
RUN useradd --uid 1000 --create-home --shell /bin/sh seed \
 && chown seed:seed /app

COPY --chown=seed:seed . .
RUN chmod +x scripts/entrypoint.sh

USER seed

EXPOSE 8080

# Compile + serve. compile.py runs at start so volume-mounted source in
# dev still produces fresh output/ on every container restart.
ENTRYPOINT ["scripts/entrypoint.sh"]
