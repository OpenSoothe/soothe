# Soothe daemon — multi-tier build with slim and full variants.
# Build context must be the monorepo root (parent of `packages/`).
#
# Slim variant (~250MB, core only):
#   docker build -f packages/soothe-daemon/Dockerfile --target slim -t soothed:slim .
#
# Full variant (~500MB, all extras + Playwright):
#   docker build -f packages/soothe-daemon/Dockerfile --target full -t soothed:full .
#
# Run (publish unified listener on 8765: WebSocket + REST):
#   docker run --rm -p 8765:8765 \
#     -e OPENAI_API_KEY=... \
#     -v soothe-data:/var/lib/soothe \
#     soothed:slim

# ========================================
# Build Arguments
# ========================================
ARG PYTHON_BASE=registry.cn-hangzhou.aliyuncs.com/lacogito/python:3.12-bookworm
ARG PYTHON_SLIM=registry.cn-hangzhou.aliyuncs.com/lacogito/python:3.12-slim-bookworm

# ========================================
# Stage 1: Builder Base (common setup)
# ========================================
FROM ${PYTHON_BASE} AS builder-base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    SOOTHE_HOME=/var/lib/soothe

RUN echo "deb http://mirrors.aliyun.com/debian/ bookworm main contrib non-free" > /etc/apt/sources.list \
    && echo "deb http://mirrors.aliyun.com/debian/ bookworm-updates main contrib non-free" >> /etc/apt/sources.list \
    && echo "deb http://mirrors.aliyun.com/debian-security/ bookworm-security main contrib non-free" >> /etc/apt/sources.list

# git needed by pip for some VCS dependencies
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency specs only (maximize cache efficiency)
COPY pyproject.toml uv.lock VERSION ./
COPY packages/soothe/pyproject.toml packages/soothe/README.md packages/soothe/
COPY packages/soothe-sdk/pyproject.toml packages/soothe-sdk/README.md packages/soothe-sdk/
COPY packages/soothe-cli/pyproject.toml packages/soothe-cli/README.md packages/soothe-cli/
COPY packages/soothe-daemon/pyproject.toml packages/soothe-daemon/README.md packages/soothe-daemon/

# Minimal source stubs for hatchling workspace builds
RUN mkdir -p packages/soothe/src/soothe \
    && : > packages/soothe/src/soothe/__init__.py \
    && mkdir -p packages/soothe-sdk/src/soothe_sdk \
    && : > packages/soothe-sdk/src/soothe_sdk/__init__.py \
    && mkdir -p packages/soothe-cli/src/soothe_cli \
    && : > packages/soothe-cli/src/soothe_cli/__init__.py \
    && mkdir -p packages/soothe-daemon/src/soothe_daemon \
    && : > packages/soothe-daemon/src/soothe_daemon/__init__.py

# ========================================
# Stage 2: Core Builder (minimal deps, ~150MB venv)
# ========================================
FROM builder-base AS builder-core

# Install core dependencies without extras
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev \
    && uv pip install soothe soothe-daemon

# Copy source code and rebuild workspace packages
COPY packages ./packages

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --force-reinstall --no-deps \
        ./packages/soothe-sdk \
        ./packages/soothe-cli \
        ./packages/soothe \
        ./packages/soothe-daemon

# ========================================
# Stage 3: Full Builder (all extras + Playwright, ~350MB venv)
# ========================================
FROM builder-base AS builder-full

# Install all extras + Playwright
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev \
    && uv pip install 'soothe[all]' soothe-daemon playwright \
    && .venv/bin/python -m playwright install chromium

# Copy source code
COPY packages ./packages

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --force-reinstall --no-deps \
        ./packages/soothe-sdk \
        ./packages/soothe-cli \
        './packages/soothe[all]' \
        ./packages/soothe-daemon

# Warmup embedding model cache (semantic similarity)
RUN mkdir -p /var/lib/soothe/data \
    && .venv/bin/soothed warmup

# ========================================
# Stage 4: Slim Runtime (~250MB)
# Core runtime only - no semantic/video/browser extras
# ========================================
FROM ${PYTHON_SLIM} AS slim

LABEL org.opencontainers.image.title="Soothe Daemon (Slim)" \
    org.opencontainers.image.description="Soothe agent orchestration daemon - core runtime only (~250MB)" \
    org.opencontainers.image.source="https://github.com/OpenSoothe/soothe"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    SOOTHE_HOME=/var/lib/soothe \
    SOOTHE_DAEMON__TRANSPORTS__WEBSOCKET__HOST=0.0.0.0 \
    SOOTHE_DAEMON__TRANSPORTS__HTTP_REST__ENABLED=true \
    SOOTHE_DAEMON__TRANSPORTS__HTTP_REST__HOST=0.0.0.0

WORKDIR /app

COPY --from=builder-core /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}"

# Create soothe user (no extra system deps needed for core)
RUN useradd --create-home --system soothe \
    && mkdir -p /var/lib/soothe \
    && chown -R soothe:soothe /var/lib/soothe

USER soothe
WORKDIR /var/lib/soothe

EXPOSE 8765/tcp

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('localhost',8765)); s.close()" || exit 1

CMD ["python", "-m", "soothe_daemon"]

# ========================================
# Stage 5: Full Runtime (~500MB)
# Feature-complete with semantic, video, browser, media extras
# ========================================
FROM ${PYTHON_BASE} AS full

LABEL org.opencontainers.image.title="Soothe Daemon (Full)" \
    org.opencontainers.image.description="Soothe agent orchestration daemon - feature-complete with semantic, video, browser, media extras" \
    org.opencontainers.image.source="https://github.com/OpenSoothe/soothe"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    SOOTHE_HOME=/var/lib/soothe \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    SOOTHE_DAEMON__TRANSPORTS__WEBSOCKET__HOST=0.0.0.0 \
    SOOTHE_DAEMON__TRANSPORTS__HTTP_REST__ENABLED=true \
    SOOTHE_DAEMON__TRANSPORTS__HTTP_REST__HOST=0.0.0.0

RUN echo "deb http://mirrors.aliyun.com/debian/ bookworm main contrib non-free" > /etc/apt/sources.list \
    && echo "deb http://mirrors.aliyun.com/debian/ bookworm-updates main contrib non-free" >> /etc/apt/sources.list \
    && echo "deb http://mirrors.aliyun.com/debian-security/ bookworm-security main contrib non-free" >> /etc/apt/sources.list

WORKDIR /app

COPY --from=builder-full /app/.venv /app/.venv
COPY --from=builder-full /opt/ms-playwright /opt/ms-playwright

ENV PATH="/app/.venv/bin:${PATH}"

# Install runtime system deps (playwright browser libs + ffmpeg for media)
RUN apt-get update \
    && /app/.venv/bin/python -m playwright install-deps \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create soothe user and directories
RUN useradd --create-home --system soothe \
    && mkdir -p /var/lib/soothe \
    && mkdir -p /home/soothe/.cache/soothe/models \
    && chown -R soothe:soothe /var/lib/soothe /opt/ms-playwright /home/soothe/.cache

# Copy embedding model cache from builder
COPY --from=builder-full --chown=soothe:soothe /root/.cache/soothe/models/huggingface /home/soothe/.cache/soothe/models/huggingface

USER soothe
WORKDIR /var/lib/soothe

EXPOSE 8765/tcp

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('localhost',8765)); s.close()" || exit 1

CMD ["python", "-m", "soothe_daemon"]