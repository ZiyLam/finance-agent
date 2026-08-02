# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.12.1 AS uv
FROM python:3.13-slim

COPY --from=uv /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    AGENT_API_HOST=0.0.0.0 \
    AGENT_API_PORT=8000 \
    AGENT_PROVIDER=echo \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY web ./web
COPY skills ./skills

RUN uv sync --locked --no-dev \
    && useradd --create-home --uid 10001 app \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "from urllib.request import urlopen; response = urlopen('http://127.0.0.1:8000/health', timeout=3); raise SystemExit(0 if response.status == 200 else 1)"

CMD ["finance-agent-api"]
