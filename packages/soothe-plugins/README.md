# Soothe Community Plugins

Standalone community plugins package for the Soothe agent orchestration framework.

## Installation

```bash
pip install soothe-plugins
```

## Available Plugins

### Sample Echo

Minimal echo subagent for testing soothe-plugins integration. See [CONTRIBUTING.md](CONTRIBUTING.md) for plugin development guide.

### Skillify (core)

Skill warehouse indexing and semantic retrieval — **built into `soothe`** (`soothe.foundation.skillify`), not this package. Enable via top-level `skillify:` in config.

### Weaver

Generative agent framework with skill harmonization. Composes skills from Skillify, resolves conflicts, and generates task-specific subagents dynamically.

### BrowserUse and Claude Code

Delegated **browser-use** and **Claude agent SDK** subagents (IG-415). Install with `pip install "soothe-plugins[browser_use]"` or `"soothe-plugins[claude]"` and enable `subagents.browser_use` / `subagents.claude` in config. Spec: `docs/RFC-601-community-agents.md`.

## Extensibility

This package is designed for extensibility. You can easily add new community plugins:

### Available Plugin Types

1. **Subagent Plugins**: Complex multi-step agents using langgraph
2. **Tool Plugins**: Simple functions exposed as tools
3. **Hybrid Plugins**: Both subagents and tools

### Future Plugins

The package structure supports adding new plugins:

```
src/soothe_plugins/
├── sample_echo/        # Minimal test subagent (example plugin)
├── paperscout/         # ArXiv paper recommendations
├── [your_plugin]/      # Your future plugin
└── [another_plugin]/   # Another future plugin
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines on adding new plugins.

### Plugin Template

Use the provided template to create new plugins:

```bash
cp -r src/soothe_plugins/.plugin_template src/soothe_plugins/your_plugin
```

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/mirasoth/soothe-plugins.git
cd soothe-plugins

# Install in development mode
pip install -e ".[dev]"
```

### Testing

```bash
# Run all tests
pytest tests/

# Run specific plugin tests
pytest tests/test_paperscout/

# With coverage
pytest tests/ --cov=src/soothe_plugins
```

### Code Quality

```bash
# Format code
ruff format src/ tests/

# Lint code
ruff check --fix src/ tests/
```

## Documentation

- **README.md**: This file - overview and quick start
- **CONTRIBUTING.md**: How to add new plugins
- **docs/RFC-601-community-agents.md**: Architecture RFC for community agents
- **src/soothe_plugins/.plugin_template/**: Template for new plugins

## Architecture

Each plugin follows the RFC-0018 plugin system:

```
Plugin Package
├── __init__.py          # @plugin, @subagent, @tool decorators
├── events.py            # Custom events (optional)
├── models.py            # Data models
├── state.py             # Agent state (if subagent)
├── implementation.py    # Core logic
└── README.md            # Plugin documentation
```

## License

MIT
