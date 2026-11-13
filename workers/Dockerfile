# syntax=docker/dockerfile:1.7
# AgentForge AI — worker image (backend code + workers/), build context: repository root
#   docker build -f workers/Dockerfile -t agentforge-ai-worker .
# One image, three services; override the command per service:
#   python -m workers.agent_worker | python -m workers.workflow_worker | python -m workers.tool_worker

ARG PYTHON_VERSION=3.12
FROM ghcr.io/astral-sh/uv:0.12.5 AS uv

FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app/backend

COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Worker-only extras (e.g. docker SDK for the tool worker)
COPY workers/requirements.txt /tmp/workers-requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /opt/venv/bin/python -r /tmp/workers-requirements.txt

# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime
LABEL org.opencontainers.image.title="agentforge-ai-worker" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/backend:/app

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder --chown=app:app /opt/venv /opt/venv
COPY --from=builder --chown=app:app /app/backend /app/backend
COPY --chown=app:app workers/ /app/workers/

USER app
# Workers expose no HTTP port; liveness = process alive + importable package
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import workers" || exit 1

CMD ["python", "-m", "workers.agent_worker"]
