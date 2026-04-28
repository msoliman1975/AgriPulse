# syntax=docker/dockerfile:1.10

# --- Builder ----------------------------------------------------------------
# Resolves and installs dependencies into a virtualenv that the runtime stage
# copies as-is. uv is used as the package manager per ARCHITECTURE.md § 3.1.
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    VIRTUAL_ENV=/opt/venv

# uv installer pins are kept here so reproducible builds don't drift.
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /uvx /usr/local/bin/

WORKDIR /build
COPY pyproject.toml ./
COPY uv.lock* ./

RUN uv venv "$VIRTUAL_ENV" \
 && uv sync --frozen --no-dev --no-install-project 2>/dev/null \
    || uv pip install --python "$VIRTUAL_ENV/bin/python" -r <(uv pip compile pyproject.toml --no-deps --no-header --quiet)

# Re-install with the project sources so editable-install metadata is correct.
COPY app ./app
COPY workers ./workers
COPY migrations ./migrations
COPY scripts ./scripts
RUN uv pip install --python "$VIRTUAL_ENV/bin/python" --no-deps .

# --- Runtime ----------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_HOME=/app

# Minimal runtime libs: libpq for psycopg, ca-certificates for outbound TLS,
# tini for proper signal handling under PID 1.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 ca-certificates tini \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 app \
 && useradd  --system --uid 10001 --gid app --home-dir "$APP_HOME" --shell /usr/sbin/nologin app \
 && mkdir -p "$APP_HOME" \
 && chown -R app:app "$APP_HOME"

COPY --from=builder --chown=app:app /opt/venv /opt/venv
COPY --chown=app:app app       "$APP_HOME/app"
COPY --chown=app:app workers   "$APP_HOME/workers"
COPY --chown=app:app migrations "$APP_HOME/migrations"
COPY --chown=app:app scripts   "$APP_HOME/scripts"

WORKDIR $APP_HOME
USER app

EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
