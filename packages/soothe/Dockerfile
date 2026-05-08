# Soothe daemon — multi-stage build.
# Build context must be the monorepo root (parent of `packages/`).
#   docker build -f packages/soothe/Dockerfile -t soothed .
#
# Run (publish WebSocket 8765 and HTTP REST 8766; mount config and data as needed):
#   docker run --rm -p 8765:8765 -p 8766:8766 \
#     -e OPENAI_API_KEY=... \
#     -v soothe-data:/var/lib/soothe \
#     soothed
#
# Layer strategy: dependency specs are copied before source code so that
# the expensive pip/playwright layers are only rebuilt when pyproject.toml
# or uv.lock change, not on every source commit.

# ---- Builder: install Python deps + Playwright browsers ----
FROM registry.cn-hangzhou.aliyuncs.com/lacogito/python:3.12-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

RUN echo "deb http://mirrors.aliyun.com/debian/ bookworm main contrib non-free" > /etc/apt/sources.list \
    && echo "deb http://mirrors.aliyun.com/debian/ bookworm-updates main contrib non-free" >> /etc/apt/sources.list \
    && echo "deb http://mirrors.aliyun.com/debian-security/ bookworm-security main contrib non-free" >> /etc/apt/sources.list

# git needed by pip for some VCS dependencies
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# ── Dependency resolution (cached unless pyproject.toml / uv.lock / VERSION change) ──
# Copy only dependency specification files — source code comes later.
COPY pyproject.toml uv.lock VERSION ./
COPY packages/soothe/pyproject.toml packages/soothe/README.md packages/soothe/
COPY packages/soothe-sdk/pyproject.toml packages/soothe-sdk/README.md packages/soothe-sdk/
COPY packages/soothe-cli/pyproject.toml packages/soothe-cli/README.md packages/soothe-cli/

# Minimal source stubs so hatchling can build workspace packages.
RUN mkdir -p packages/soothe/src/soothe \
    && : > packages/soothe/src/soothe/__init__.py \
    && mkdir -p packages/soothe-sdk/src/soothe_sdk \
    && : > packages/soothe-sdk/src/soothe_sdk/__init__.py \
    && mkdir -p packages/soothe-cli/src/soothe_cli \
    && : > packages/soothe-cli/src/soothe_cli/__init__.py

# Install all Python deps + Playwright browser (EXPENSIVE — cached by dep changes only)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev \
    && uv pip install 'soothe[all]' playwright \
    && .venv/bin/python -m playwright install chromium

# ── Source code (invalidated on any source change) ──────────────────
# Overwrites the stubs; workspace packages rebuilt quickly because all
# third-party deps are already in .venv.
COPY packages ./packages
COPY scripts/warmup_semantic.py ./scripts/warmup_semantic.py

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --force-reinstall --no-deps \
        ./packages/soothe-sdk \
        ./packages/soothe-cli \
        './packages/soothe[all]'

# Warmup semantic similarity model to avoid latency on first use
RUN .venv/bin/python scripts/warmup_semantic.py

# ---- Runtime: minimal image with .venv + browsers ----
FROM registry.cn-hangzhou.aliyuncs.com/lacogito/python:3.12-bookworm

LABEL org.opencontainers.image.title="Soothe Daemon" \
    org.opencontainers.image.description="Soothe agent orchestration daemon (full optional extras)" \
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

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /opt/ms-playwright /opt/ms-playwright

ENV PATH="/app/.venv/bin:${PATH}"

# Install only runtime system deps (playwright browser libs + ffmpeg)
RUN apt-get update \
    && /app/.venv/bin/python -m playwright install-deps \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --system soothe \
    && mkdir -p /var/lib/soothe \
    && chown -R soothe:soothe /var/lib/soothe /opt/ms-playwright

USER soothe
WORKDIR /var/lib/soothe

EXPOSE 8765/tcp 8766/tcp

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('localhost',8765)); s.close()" || exit 1

CMD ["python", "-m", "soothe.daemon"]
