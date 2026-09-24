# syntax=docker/dockerfile:1
# acme-api image: python slim + a uv-built venv, no uv/pip/compilers in the runtime stage.
# Build from the workspace root: docker build -t acme-api .
# (Distroless python3 is Debian's Python 3.13, so it can't run a 3.14 venv; stay on slim.)

FROM python:3.14.7-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src

# 1. Third-party dependencies only: cached until uv.lock changes.
#    --frozen because the member pyproject files aren't in this layer yet.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-workspace --package acme-api

# 2. The workspace members this service needs, installed as real (non-editable) packages,
#    and --locked so a stale uv.lock fails the build instead of silently re-resolving.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable --package acme-api

FROM python:3.14.7-slim-trixie
# Same base image as the build stage: the venv's python symlinks to /usr/local/bin/python3.14.
RUN groupadd --system --gid 999 app && useradd --system --uid 999 --gid app --no-create-home app
COPY --from=build --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8000
USER app
WORKDIR /app
EXPOSE 8000
# Exec form so SIGTERM reaches the process (uvicorn drains, then runs lifespan shutdown).
CMD ["acme-api", "serve"]
