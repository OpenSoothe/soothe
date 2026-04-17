# Standalone Package Migration Guide

This document describes how to migrate soothe_sdk to a standalone repository.

## Current Status

The `soothe-sdk` package is currently located in the Soothe monorepo at:
- `sdk/` - Standalone package structure
- `src/soothe_sdk/` - Original location (to be removed after migration)

## Migration Steps

### 1. Create Standalone Repository

```bash
# Create new repository on GitHub/GitLab
# Repository: soothe-sdk

# Clone the standalone package structure
git clone <soothe-repo>
cd soothe

# Copy standalone package to new location
cp -r sdk ../soothe-sdk/
cd ../soothe-sdk
git init
git add .
git commit -m "Initial commit: soothe-sdk standalone package"
git remote add origin <soothe-sdk-repo-url>
git push -u origin main
```

### 2. Remove from Soothe Monorepo

After the standalone package is tested and working:

```bash
# In Soothe monorepo
rm -rf src/soothe_sdk
rm -rf sdk
```

### 3. Update Soothe Dependencies

Update `pyproject.toml` in Soothe monorepo:

```toml
dependencies = [
    # ... existing dependencies ...
    "soothe-sdk>=0.1.0,<1.0.0",
]
```

### 4. Update Soothe Documentation

Add to Soothe's README.md:

```markdown
## Plugin Development

To develop plugins for Soothe, use the soothe-sdk package:

```bash
pip install soothe-sdk
```

See [soothe-sdk](https://github.com/caesar0301/soothe-sdk) for details.
```

### 5. Publish to PyPI

```bash
# Build the package
cd soothe-sdk
python -m build

# Upload to PyPI
twine upload dist/*
```

### 6. Verify Installation

```bash
# Install from PyPI
pip install soothe-sdk

# Verify import
python -c "from soothe_sdk.plugin import plugin, tool, subagent; print('OK')"

# Test with Soothe plugin
python -c "from soothe.plugin.global_registry import load_plugins; print('OK')"
```

## Directory Structure (v0.4.0)

```
soothe-sdk/
├── README.md
├── pyproject.toml
├── .gitignore
├── src/
│   └── soothe_sdk/
│       ├── __init__.py           # Minimal (version only)
│       ├── events.py             # Core concept at root
│       ├── exceptions.py         # Core concept at root
│       ├── verbosity.py          # Core concept at root
│       ├── protocols/            # Protocol definitions
│       ├── client/               # Client utilities
│       │   ├── protocol.py
│       │   ├── websocket_client.py
│       │   └── config.py         # Merged constants + types
│       ├── plugin/               # Plugin API
│       │   ├── decorators.py     # Merged @plugin, @tool, @subagent
│       │   ├── manifest.py
│       │   ├── context.py
│       │   ├── health.py
│       │   ├── registry.py
│       │   └── emit.py
│       ├── ux/                   # UX/display helpers
│       ├── utils/                # Shared utilities
│       └── types/                # Deprecated (empty)
└── tests/
    ├── conftest.py
    ├── test_decorators.py
    ├── test_types.py
    └── test_integration.py
```

## Usage

After installing soothe-sdk:

```python
from soothe_sdk.plugin import plugin, tool, subagent

@plugin(name="my-plugin", version="1.0.0", description="My plugin")
class MyPlugin:
    @tool(name="greet", description="Greet someone")
    def greet(self, name: str) -> str:
        return f"Hello, {name}!"
```

## Development

For SDK development:

```bash
# Clone the repo
git clone <soothe-sdk-repo>
cd soothe-sdk

# Install in dev mode
pip install -e ".[dev]"

# Run tests
pytest tests/

# Type checking
mypy src/soothe_sdk/

# Format and lint
ruff format src/ tests/
ruff check --fix src/ tests/
```

## Dependencies

The SDK maintains minimal dependencies:

- **pydantic>=2.0.0**: For data validation and settings management
- **langchain-core>=1.2.0**: For tool and subagent base types

## Version Compatibility

The SDK declares compatibility with Soothe:

```python
__soothe_required_version__ = ">=0.1.0,<1.0.0"
```

## Support

- **Issues**: <soothe-sdk-repo>/issues
- **Documentation**: <soothe-sdk-repo>/README.md
- **Soothe Docs**: <soothe-repo>/docs/