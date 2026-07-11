# Soothe tests

## Layout

| Directory | Purpose | CI (`verify_finally.sh`) |
|-----------|---------|--------------------------|
| `tests/unit/` | Fast, isolated tests (mocks, `tmp_path`, in-memory SQLite) | **Yes** — default |
| `tests/integration/` | External services (Postgres, LLM APIs, network search) | **No** — run manually |

## Running

```bash
# Default unit suite (matches CI)
cd packages/soothe && uv run pytest tests/unit/

# Integration suite (Postgres at 127.0.0.1:6432, API keys, etc.)
uv run pytest tests/integration/ --run-integration

# Single integration-marked test under unit/
uv run pytest tests/unit/core/resolver/test_shared_checkpointer_pool.py --run-integration
```

## Classification rules

- **Unit** — no live Postgres/LLM/network; completes in seconds; uses mocks or local temp dirs.
- **Integration** — lives under `tests/integration/` **or** carries `@pytest.mark.integration` when it needs real infrastructure.

Shared fixtures (`test_config`, `integration_config`, `soothe_runner`) live in `tests/conftest.py`.
