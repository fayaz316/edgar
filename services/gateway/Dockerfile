# Multi-stage, non-root, uv-managed. Build target = the CI image too.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
WORKDIR /app
COPY pyproject.toml ./
RUN uv venv /app/.venv && uv pip install --python /app/.venv/bin/python fastapi uvicorn pydantic pydantic-settings structlog

FROM gcr.io/distroless/python3-debian12:nonroot
COPY --from=build /app/.venv /app/.venv
COPY services/gateway/main.py /app/services/gateway/main.py
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
WORKDIR /app/services/gateway
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
