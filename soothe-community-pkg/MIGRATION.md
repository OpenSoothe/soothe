# Standalone Package Migration Guide

This document describes how to migrate soothe_community to a standalone repository.

## Current Status

The `soothe-community` package is currently located in the Soothe monorepo at:
- `soothe-community-pkg/` - Standalone package structure
- `src/soothe_community/` - Original location (to be removed after migration)

## Migration Steps

### 1. Create Standalone Repository

```bash
# Create new repository on GitHub/GitLab
# Repository: soothe-community

# Clone the standalone package structure
git clone <soothe-repo>
cd soothe

# Copy standalone package to new location
cp -r soothe-community-pkg ../soothe-community/
cd ../soothe-community
git init
git add .
git commit -m "Initial commit: soothe-community standalone package"
git remote add origin <soothe-community-repo-url>
git push -u origin main
```

### 2. Remove from Soothe Monorepo

After the standalone package is tested and working:

```bash
# In Soothe monorepo
rm -rf src/soothe_community
rm -rf tests/unit/community
rm -rf soothe-community-pkg
```

### 3. Update Soothe Documentation

Add to Soothe's README.md:

```markdown
## Community Plugins

Third-party plugins are available in separate packages:

- [soothe-community](https://github.com/caesar0301/soothe-community) - PaperScout and other community plugins

Install with:
\`\`\`bash
pip install soothe-community
\`\`\`
```

### 4. Publish to PyPI

```bash
# Build the package
cd soothe-community
python -m build

# Upload to PyPI
twine upload dist/*
```

### 5. Verify Installation

```bash
# Install from PyPI
pip install soothe-community

# Verify plugin discovery
python -c "from soothe.plugin.global_registry import load_plugins; print('OK')"

# Test with Soothe
soothe checkhealth
```

## Directory Structure

```
soothe-community/
├── README.md
├── pyproject.toml
├── .gitignore
├── src/
│   └── soothe_community/
│       ├── __init__.py
│       └── paperscout/
│           ├── __init__.py
│           ├── events.py
│           ├── models.py
│           ├── state.py
│           ├── nodes.py
│           ├── reranker.py
│           ├── email.py
│           ├── gap_scanner.py
│           └── implementation.py
└── tests/
    └── test_paperscout/
        ├── conftest.py
        ├── test_events.py
        ├── test_models.py
        ├── test_plugin.py
        ├── test_reranker.py
        └── test_email.py
```

## Configuration Example

Users can configure PaperScout in their Soothe config.yml:

```yaml
# ~/.soothe/config.yml
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
        library_type: "user"
```

## Usage

After installing soothe-community:

```bash
# Run PaperScout
soothe "Find recent papers on transformer architectures" --subagent paperscout

# Check plugin is loaded
soothe checkhealth
```

## Development

For plugin development:

```bash
# Clone the repo
git clone <soothe-community-repo>
cd soothe-community

# Install in dev mode
pip install -e ".[dev]"

# Run tests
pytest tests/

# Format and lint
ruff format src/ tests/
ruff check --fix src/ tests/
```

## Adding New Plugins

To add a new plugin to soothe-community:

1. Create package: `src/soothe_community/your_plugin/`
2. Add plugin class with `@plugin` decorator
3. Add subagent(s) with `@subagent` decorator
4. Register in `pyproject.toml`:
   ```toml
   [project.entry-points."soothe.plugins"]
   your_plugin = "soothe_community.your_plugin:YourPlugin"
   ```
5. Add tests in `tests/test_your_plugin/`
6. Update README with plugin documentation

## Support

- **Issues**: <soothe-community-repo>/issues
- **Documentation**: <soothe-community-repo>/README.md
- **Soothe Docs**: <soothe-repo>/docs/
