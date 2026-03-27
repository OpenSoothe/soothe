# Soothe Community Plugins

Standalone community plugins package for the Soothe agent orchestration framework.

## Installation

```bash
pip install soothe-community
```

## Available Plugins

### PaperScout

ArXiv paper recommendation agent that delivers personalized daily paper recommendations.

**Features**:
- Fetches papers from ArXiv based on configurable categories
- Analyzes your Zotero library to understand research interests
- Ranks papers by relevance using sentence embeddings
- Sends daily email digests with TLDR summaries

**Configuration** (add to your Soothe config.yml):

```yaml
subagents:
  paperscout:
    enabled: true
    model: "openai:gpt-4o-mini"
    config:
      arxiv_categories:
        - cs.AI
        - cs.CV
        - cs.LG
      max_papers: 25
      smtp:
        host: "${SMTP_HOST}"
        port: 587
        user: "${SMTP_USER}"
        password: "${SMTP_PASSWORD}"
      zotero:
        api_key: "${ZOTERO_API_KEY}"
        library_id: "${ZOTERO_LIBRARY_ID}"
```

**Usage**:

```bash
# Use the subagent via TUI (default)
soothe "Find recent papers on transformers" --subagent paperscout

# Or use in headless mode
soothe "Find recent papers on transformers" --subagent paperscout --no-tui
```

## Extensibility

This package is designed for extensibility. You can easily add new community plugins:

### Available Plugin Types

1. **Subagent Plugins**: Complex multi-step agents using langgraph
2. **Tool Plugins**: Simple functions exposed as tools
3. **Hybrid Plugins**: Both subagents and tools

### Future Plugins

The package structure supports adding new plugins:

```
src/soothe_community/
├── paperscout/         # ArXiv paper recommendations
├── [your_plugin]/      # Your future plugin
└── [another_plugin]/   # Another future plugin
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines on adding new plugins.

### Plugin Template

Use the provided template to create new plugins:

```bash
cp -r src/soothe_community/.plugin_template src/soothe_community/your_plugin
```

## Development

### Setup

```bash
# Clone the repository
git clone <soothe-community-repo>
cd soothe-community

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
pytest tests/ --cov=src/soothe_community
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
- **MIGRATION.md**: Guide for migrating to standalone repository
- **src/soothe_community/.plugin_template/**: Template for new plugins

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
