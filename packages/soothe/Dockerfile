# Soothe daemon — full optional capabilities (soothe[all]), community package, Playwright/Chromium.
# Build context must be the monorepo root (parent of `packages/`). Docker reads `.dockerignore`
# from the context root only (repository root), not from this directory.
#   docker build -f packages/soothe/Dockerfile -t soothe-daemon .
#
# Run (publish WebSocket 8765 and HTTP REST 8766; mount config and data as needed):
#   docker run --rm -p 8765:8765 -p 8766:8766 \
#     -e OPENAI_API_KEY=... \
#     -v soothe-data:/var/lib/soothe \
#     soothe-daemon

FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="Soothe Daemon" \
    org.opencontainers.image.description="Soothe agent orchestration daemon (full optional extras)" \
    org.opencontainers.image.source="https://github.com/caesar0301/soothe"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    SOOTHE_HOME=/var/lib/soothe \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    # Listen on all interfaces inside the container
    SOOTHE_DAEMON__TRANSPORTS__WEBSOCKET__HOST=0.0.0.0 \
    SOOTHE_DAEMON__TRANSPORTS__HTTP_REST__ENABLED=true \
    SOOTHE_DAEMON__TRANSPORTS__HTTP_REST__HOST=0.0.0.0

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    ffmpeg \
    git \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Workspace root + all member packages (required for uv.lock resolution)
COPY pyproject.toml uv.lock VERSION ./
COPY packages ./packages

RUN uv sync --all-extras --no-dev --frozen \
    && .venv/bin/python -m playwright install-deps \
    && .venv/bin/python -m playwright install chromium \
    && useradd --create-home --system soothe \
    && mkdir -p /var/lib/soothe \
    && chown -R soothe:soothe /app/.venv /var/lib/soothe /opt/ms-playwright

ENV PATH="/app/.venv/bin:${PATH}"

USER soothe
WORKDIR /var/lib/soothe

EXPOSE 8765/tcp 8766/tcp

CMD ["python", "-m", "soothe.daemon"]
