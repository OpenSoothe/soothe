# syntax=docker/dockerfile:1
# Soothe daemon — production runtime image (PyPI installs + deps + embedding cache warmup).
#
# Build context must be the monorepo root (parent of `packages/`) so `scripts/warmup_embedding_model.py`
# can be copied. Published wheels are installed from PyPI (same as end users).
#
# Build (full image with browser subagent):
#   docker build -f packages/soothe-daemon/Dockerfile \
#     --build-arg SOOTHE_VERSION=0.5.8 \
#     -t soothed:latest .
#
# Build (slim image without browser subagent):
#   docker build -f packages/soothe-daemon/Dockerfile \
#     --build-arg SOOTHE_VERSION=0.5.8 \
#     --build-arg INCLUDE_BROWSER=false \
#     -t soothed:slim .
#
# `soothe[all]` is pinned to SOOTHE_VERSION. `soothe-daemon` defaults to the
# latest PyPI release compatible with that pin (PyPI may lag: newer soothe
# patch, older daemon-only release). Override when you need an exact daemon:
#   --build-arg SOOTHE_DAEMON_VERSION=0.5.6
#
# Optional: use a custom Python base (e.g. internal mirror):
#   --build-arg PYTHON_BASE=registry.example.com/python:3.12-bookworm
#
# Run (unified listener on 8765: WebSocket + REST):
#   docker run --rm -p 8765:8765 \
#     -e OPENAI_API_KEY=... \
#     -v soothe-data:/var/lib/soothe \
#     soothed:latest

ARG PYTHON_BASE=registry.cn-hangzhou.aliyuncs.com/lacogito/python:3.12-bookworm

# =============================================================================
# Stage 1: install wheels, browsers (optional), system libs, warm embedding cache
# =============================================================================
FROM ${PYTHON_BASE} AS deps

ARG SOOTHE_VERSION=0.5.8
# Empty = latest soothe-daemon on PyPI compatible with pinned soothe[all].
ARG SOOTHE_DAEMON_VERSION=
# Include browser subagent dependencies (playwright/chromium). Default: true.
ARG INCLUDE_BROWSER=true

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    SOOTHE_HOME=/var/lib/soothe

RUN sed -i 's|http://deb.debian.org|http://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv directly via curl (avoids ghcr.io access for networks with restrictions)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv

# Ensure playwright browsers directory exists (empty if INCLUDE_BROWSER=false)
RUN mkdir -p /opt/ms-playwright

RUN --mount=type=cache,target=/root/.cache/uv \
    set -eux; \
    if [ -n "${SOOTHE_DAEMON_VERSION}" ]; then \
      dspec="soothe-daemon==${SOOTHE_DAEMON_VERSION}"; \
    else \
      dspec="soothe-daemon"; \
    fi; \
    if [ "${INCLUDE_BROWSER}" = "true" ]; then \
      extras="all"; \
      pip_extras="playwright sentence_transformers"; \
    else \
      extras="research,tabular,document,github,dashscope,semantic,langfuse,claude"; \
      pip_extras=""; \
    fi; \
    uv venv /app/.venv; \
    uv pip install --python /app/.venv/bin/python \
        "soothe[${extras}]==${SOOTHE_VERSION}" \
        "${dspec}" \
        ${pip_extras}; \
    if [ "${INCLUDE_BROWSER}" = "true" ]; then \
      /app/.venv/bin/python -m playwright install chromium; \
    fi

ENV SOOTHE_HF_CACHE=/root/.cache/soothe/models/huggingface
COPY scripts/warmup_embedding_model.py /tmp/warmup_embedding_model.py
# Warmup is optional - model downloads at runtime if cache miss
RUN /app/.venv/bin/python /tmp/warmup_embedding_model.py --verbose || echo "Embedding warmup skipped (will download at runtime)" \
    && rm -f /tmp/warmup_embedding_model.py

ENV PATH="/app/.venv/bin:${PATH}"

# =============================================================================
# Stage 2: minimal runtime (venv + browsers (optional) + HF cache, non-root)
# =============================================================================
FROM ${PYTHON_BASE} AS runtime

ARG SOOTHE_VERSION=0.5.8
ARG INCLUDE_BROWSER=true

LABEL org.opencontainers.image.title="Soothe Daemon" \
    org.opencontainers.image.description="Soothe agent orchestration daemon (PyPI soothe-daemon + bundled deps)" \
    org.opencontainers.image.source="https://github.com/OpenSoothe/soothe" \
    org.opencontainers.image.version="${SOOTHE_VERSION}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILEBYTECODE=1 \
    SOOTHE_HOME=/var/lib/soothe \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    SOOTHE_DAEMON_TRANSPORTS__WEBSOCKET__HOST=0.0.0.0 \
    SOOTHE_DAEMON_TRANSPORTS__HTTP_REST__ENABLED=true \
    SOOTHE_DAEMON_TRANSPORTS__HTTP_REST__HOST=0.0.0.0

WORKDIR /app

COPY --from=deps /app/.venv /app/.venv
COPY --from=deps /opt/ms-playwright /opt/ms-playwright

ENV PATH="/app/.venv/bin:${PATH}"

RUN sed -i 's|http://deb.debian.org|http://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && if [ "${INCLUDE_BROWSER}" = "true" ] && [ -n "$(ls -A /opt/ms-playwright 2>/dev/null)" ]; then \
      /app/.venv/bin/python -m playwright install-deps; \
    fi \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --system soothe \
    && mkdir -p /var/lib/soothe \
    && mkdir -p /home/soothe/.cache/soothe/models \
    && chown -R soothe:soothe /var/lib/soothe /opt/ms-playwright /home/soothe/.cache

COPY --from=deps --chown=soothe:soothe /root/.cache/soothe/models/huggingface /home/soothe/.cache/soothe/models/huggingface

USER soothe
WORKDIR /var/lib/soothe

EXPOSE 8765/tcp

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('localhost',8765)); s.close()" || exit 1

CMD ["python", "-m", "soothe_daemon"]