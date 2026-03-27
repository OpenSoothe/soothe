# Soothe Community Plugins

Welcome to the Soothe Community Plugins repository! This package contains
community-contributed plugins for the Soothe agent orchestration framework.

## What Are Community Plugins?

Community plugins are third-party extensions that add new capabilities to Soothe
without modifying the core framework. They follow the RFC-0018 Plugin Extension
System specification.

## Available Plugins

### PaperScout (`paperscout`)

ArXiv paper recommendation agent that delivers personalized daily paper
recommendations by analyzing your Zotero library.

**Features**:
- Fetches papers from ArXiv based on configurable categories
- Analyzes your Zotero library to understand research interests
- Ranks papers by relevance using sentence embeddings
- Sends daily email digests with TLDR summaries
- Discovers code repositories via PapersWithCode

**Installation**:
```bash
pip install soothe[paperscout]
```

**Configuration**:
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
# Use via TUI (default)
soothe "Find recent papers on transformer architectures" --subagent paperscout

# Or headless mode
soothe "Find recent papers" --subagent paperscout --no-tui
```

## Creating a New Plugin

To create a new community plugin:

1. **Create a package** in `src/soothe_community/your_plugin/`
2. **Define events** in `events.py` using `register_event()`
3. **Create plugin class** in `__init__.py` with `@plugin` decorator
4. **Implement functionality** in `implementation.py`
5. **Add tests** in `tests/unit/community/test_your_plugin/`
6. **Update dependencies** in `pyproject.toml` (optional extras)

See the PaperScout plugin for a complete example.

## Plugin Development Guidelines

### 1. Follow RFC-0018

All plugins must comply with RFC-0018 Plugin Extension System:
- Use `@plugin` decorator for plugin registration
- Use `@tool` or `@subagent` decorators for capabilities
- Register custom events using `register_event()`
- Respect trust levels and permissions

### 2. Self-Containment

Each plugin should be self-contained:
- Define its own events in `events.py`
- Include all necessary data models
- Handle configuration through Soothe's config system
- Document dependencies clearly

### 3. Testing

- Provide comprehensive test coverage (>80%)
- Mock all external APIs and services
- Test plugin lifecycle (load/unload)
- Test event emission

### 4. Documentation

- Create a README for the plugin
- Document configuration options
- Provide usage examples
- List dependencies and installation requirements

### 5. Code Quality

- Follow Soothe's Python style guide
- Use type hints on all public functions
- Add Google-style docstrings
- Run `./scripts/verify_finally.sh` before committing

## Directory Structure

```
src/soothe_community/
├── __init__.py              # Package init
├── README.md                # This file
└── paperscout/              # Example plugin
    ├── __init__.py          # Plugin registration
    ├── events.py            # Event definitions
    ├── implementation.py    # Core implementation
    ├── state.py             # Configuration/state models
    ├── nodes.py             # Workflow nodes
    ├── reranker.py          # Paper ranking
    ├── email.py             # Email formatting
    ├── models.py            # Data models
    └── gap_scanner.py       # Gap detection
```

## Contributing

To contribute a plugin:

1. Fork the repository
2. Create your plugin in `src/soothe_community/your_plugin/`
3. Add tests in `tests/unit/community/test_your_plugin/`
4. Update this README with your plugin's documentation
5. Submit a pull request

## Support

- **Documentation**: See `docs/specs/RFC-0018.md` for plugin architecture
- **Examples**: See existing plugins in this directory
- **Issues**: Report issues on GitHub

## License

Community plugins follow the same license as the main Soothe project.
