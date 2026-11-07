# Build context = REPO ROOT:  docker build -f services/gateway/Dockerfile -t edgar-gateway:dev .
# Dependencies come from uv.lock (hash-pinned) — never `pip install <loose names>`.
# Both stages are Docker-official python images (same interpreter path, so the
# copied venv's symlinks resolve); runtime runs as a non-root user.
FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim-bookworm
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY services/__init__.py services/__init__.py
COPY services/gateway services/gateway
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8080
CMD ["uvicorn", "services.gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
