# Soothe

Multi-agent harness built on deepagents and langchain/langgraph.

## Installation

This project uses [uv](https://docs.astral.sh/uv/) for fast Python package management.

### Prerequisites

- Python 3.11+
- uv (install with `curl -LsSf https://astral.sh/uv/install.sh | sh`)

### Setup

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd soothe
   ```

2. Sync dependencies:
   ```bash
   make sync
   ```

3. For development (includes test and lint tools):
   ```bash
   make sync-dev
   ```

## Development

### Available Commands

Run `make help` to see all available commands:

- `make sync` - Sync dependencies
- `make sync-dev` - Sync dev dependencies
- `make format` - Format code with ruff
- `make lint` - Lint code with ruff
- `make test` - Run tests with pytest
- `make build` - Build the package
- `make clean` - Clean build artifacts

### Running Tests

```bash
make test
```

Or directly with uv:
```bash
uv run pytest tests/ -v
```

### Code Style

This project uses [ruff](https://docs.astral.sh/ruff/) for formatting and linting.

Format code:
```bash
make format
```

Lint code:
```bash
make lint
```

## Project Structure

- `src/soothe/` - Main source code
- `tests/` - Test suite
- `docs/` - Documentation
- `examples/` - Example usage

## Privacy and Security

The Browser subagent uses the [browser-use](https://github.com/browser-use/browser-use) library with **privacy-first defaults**. By default, the following features are disabled:

- **Browser extensions**: uBlock Origin, "I still don't care about cookies", and ClearURLs are not loaded
- **Cloud services**: No connections to api.browser-use.com or llm.api.browser-use.com
- **Anonymous telemetry**: No usage data is sent to PostHog (eu.i.posthog.com)

These defaults protect your privacy and reduce network traffic. If you need these features, you can re-enable them when creating the subagent:

```python
from soothe import SootheConfig, create_soothe_agent

config = SootheConfig(
    subagents={
        "browser": {
            "enabled": True,
            "disable_extensions": False,  # Enable browser extensions
            "disable_cloud": False,        # Enable cloud features
            "disable_telemetry": False,    # Enable anonymous telemetry
        }
    }
)
```

Or when using the factory function directly:

```python
from soothe.subagents.browser import create_browser_subagent

subagent = create_browser_subagent(
    disable_extensions=False,
    disable_cloud=False,
    disable_telemetry=False,
)
```

## License

MIT