# Soothe Community Package Structure

This document describes the final polished structure of the soothe-community package.

## Package Layout

```
soothe-community-pkg/
├── .gitignore                    # Git ignore patterns
├── CONTRIBUTING.md               # Guide for contributors
├── MIGRATION.md                  # Migration guide for standalone repo
├── README.md                     # Package overview
├── pyproject.toml                # Package configuration
├── src/
│   └── soothe_community/
│       ├── __init__.py          # Package initialization
│       ├── paperscout/          # PaperScout plugin
│       │   ├── __init__.py      # Plugin class
│       │   ├── email.py         # Email functionality
│       │   ├── events.py        # Custom events
│       │   ├── gap_scanner.py   # Gap scanning
│       │   ├── implementation.py # Subagent creation
│       │   ├── models.py        # Data models
│       │   ├── nodes.py         # Graph nodes
│       │   ├── reranker.py      # Reranking logic
│       │   └── state.py         # State definitions
│       ├── .plugin_template/    # Template for new plugins
│       │   ├── PLUGIN_TEMPLATE.md
│       │   ├── __init__.py.template
│       │   ├── events.py.template
│       │   ├── models.py.template
│       │   ├── state.py.template
│       │   ├── implementation.py.template
│       │   └── README.md.template
│       └── README.md            # Package-level README
└── tests/
    ├── conftest.py              # Shared test fixtures
    └── test_paperscout/         # PaperScout tests
        ├── conftest.py
        ├── test_email.py
        ├── test_events.py
        ├── test_models.py
        ├── test_plugin.py
        └── test_reranker.py
```

## Key Features

### 1. Clean Package Structure
- No nested directories
- Proper `src/` layout following Python packaging best practices
- Tests colocated with package

### 2. Extensibility
- Plugin template directory with all necessary files
- Clear documentation for adding new plugins
- CONTRIBUTING.md with detailed guidelines

### 3. Testing
- All tests moved from main Soothe project
- Shared fixtures in `tests/conftest.py`
- Plugin-specific fixtures in each test directory

### 4. Documentation
- **README.md**: Quick start and overview
- **CONTRIBUTING.md**: How to contribute and add plugins
- **MIGRATION.md**: Standalone repository migration guide
- **Plugin READMEs**: Each plugin has its own documentation

### 5. Build Configuration
- Proper `pyproject.toml` with all metadata
- Entry points for plugin discovery
- Development dependencies
- Ruff configuration for code quality

## Usage

### Installation

```bash
pip install soothe-community
```

### Development Installation

```bash
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest tests/
```

### Adding a New Plugin

1. Copy the template:
   ```bash
   cp -r src/soothe_community/.plugin_template src/soothe_community/your_plugin
   ```

2. Rename and update template files

3. Register in `pyproject.toml`:
   ```toml
   [project.entry-points."soothe.plugins"]
   your_plugin = "soothe_community.your_plugin:YourPlugin"
   ```

4. Add tests in `tests/test_your_plugin/`

5. Update README with plugin documentation

## Extensibility Points

The package is designed to support:

1. **Multiple Plugins**: Add new plugins without modifying existing code
2. **Plugin Types**: Support subagents, tools, or hybrid plugins
3. **Custom Events**: Each plugin can define its own events
4. **Independent Testing**: Each plugin has isolated tests
5. **Documentation**: Each plugin has its own README

## Next Steps

This package is ready for:

1. **Testing**: Verify all tests pass
2. **Distribution**: Publish to PyPI
3. **Migration**: Move to standalone repository if desired
4. **Extension**: Add new community plugins

## Verification Checklist

- [x] Clean directory structure (no nested soothe-community-pkg/)
- [x] Source files in `src/soothe_community/`
- [x] Tests moved from main Soothe project
- [x] Plugin template created
- [x] CONTRIBUTING.md with detailed guidelines
- [x] Updated README with extensibility information
- [x] Proper pyproject.toml configuration
- [x] All template files created
- [ ] Tests passing (requires pytest installation)
- [ ] Package installable with `pip install -e .`

## Success Metrics

The package structure is complete and ready for:

1. Independent development and testing
2. Addition of new community plugins
3. Distribution as a standalone package
4. Migration to separate repository if desired