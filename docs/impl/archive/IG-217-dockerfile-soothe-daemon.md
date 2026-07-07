# IG-217: Docker image for Soothe daemon

**Status:** In progress  
**Purpose:** Track adding a production-oriented `Dockerfile` that builds the monorepo workspace with `soothe[all]` (all optional daemon capabilities), Playwright/Chromium for the browser subagent, and sensible defaults for container networking.

**Deliverables**

- `packages/soothe/Dockerfile` (build context = monorepo root; `docker build -f packages/soothe/Dockerfile .`).
- `.dockerignore` at the repository root (used when context is `.`; Docker does not read a `.dockerignore` next to this Dockerfile).
- Image runs `python -m soothe.daemon` in the foreground with WebSocket and HTTP REST bound to `0.0.0.0`.

**Notes**

- Dependencies: `uv sync --all-extras --no-dev --frozen` against the workspace `uv.lock`.
- Browser automation: `playwright install-deps` + `playwright install chromium` after sync.
- Persistence: `SOOTHE_HOME` defaults to `/var/lib/soothe` (mount a volume as needed).
