FROM ghcr.io/astral-sh/uv:0.12.9 AS uv
FROM python:3.11-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --extra service --no-dev --no-install-project --no-cache
COPY src ./src
COPY scripts ./scripts
RUN useradd --uid 10001 --create-home service && mkdir /work && chown service:service /work
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_NO_CACHE=1
USER service
CMD ["uvicorn", "src.service_layer.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
