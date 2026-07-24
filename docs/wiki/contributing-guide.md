---
title: Contributing Guide
parent: Development & Contributing
nav_order: 1
description: >-
  Development workflow, code standards, and contribution process.
---

# Contributing Guide

Welcome to Soothe! This guide covers development workflow, code standards, and contribution process.

---

## Table of Contents

1. [Development Setup](#development-setup)
2. [Code Standards](#code-standards)
3. [Development Workflow](#development-workflow)
4. [Pull Request Process](#pull-request-process)
5. [Architecture Guidelines](#architecture-guidelines)
6. [Commit Guidelines](#commit-guidelines)

---

## Development Setup

### Prerequisites

- **Python 3.11+** (required)
- **uv** package manager (recommended)
- **Docker** (for integration tests)
- **Git** (for version control)

### Initial Setup

1. **Clone the repository**:
```bash
git clone https://github.com/mirasoth/soothe.git
cd soothe
```

2. **Sync dependencies**:
```bash
# Sync all packages with all extras and dev dependencies
make sync

# Or manually
uv sync --all-packages --all-extras
```

3. **Verify setup**:
```bash
# Run verification script
./scripts/verify_finally.sh

# Should see:
# ✅ All checks passed
```

4. **Start development services** (optional, for integration tests):
```bash
# PostgreSQL + pgvector + Langfuse (dev stack)
docker compose -f docker-compose.yml up -d
```

### Workspace Structure

This monorepo **owns** three packages (format / lint / test / publish here):

```
packages/
├── soothe-cli/        # CLI + TUI
├── soothe/            # Agent core (library)
└── soothe-daemon/     # Daemon server
```

Submodules are **consumed only** (do not format, lint, test, or release them here):

- `packages/soothe-sdk` — [mirasoth/soothe-sdk](https://github.com/mirasoth/soothe-sdk)
- `packages/soothe-nano` — [mirasoth/soothe-nano](https://github.com/mirasoth/soothe-nano)
- `client/{python,go,typescript,rust}` — language clients
- `apps/soothe-desktop`

Community plugins ship from [mirasoth/soothe-plugins](https://github.com/mirasoth/soothe-plugins).

**Dependency order** (imports):
```
soothe-sdk → soothe-nano → soothe → soothe-daemon
soothe-sdk → soothe-client-python → soothe-cli
```

**Rules** (owned packages):
- **CLI**: Can import SDK + client, **NOT** soothe/daemon
- **soothe**: Can import SDK + nano, **NOT** daemon
- **daemon**: Can import soothe + SDK (+ nano via soothe); **NOT** CLI/client

---

## Code Standards

### Python Style

- **Python >=3.11**
- **Type hints** on all public functions
- **Google-style docstrings** with Args, Returns, Raises
- **Ruff** for linting and formatting
- **No bare `except:`** - use typed exception handling

### Docstring Format

```python
def my_function(arg: str, optional: int = 0) -> dict:
    """Brief description of function.

    Args:
        arg: Description of arg.
        optional: Description of optional parameter.

    Returns:
        Description of return value.

    Raises:
        ValueError: When arg is invalid.

    Example:
        >>> result = my_function("test")
        >>> print(result)
    """
    pass
```

### Single Backticks

Use single backticks for inline code in docstrings:

```python
# ✅ Good
"""Use `create_agent()` to instantiate."""

# ❌ Bad (Sphinx double backticks)
"""Use ``create_agent()`` to instantiate."""
```

### Naming Conventions

- **Modules**: `snake_case` (e.g., `strange_loop.py`)
- **Classes**: `PascalCase` (e.g., `StrangeLoop`)
- **Functions**: `snake_case` (e.g., `create_agent`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `MAX_ITERATIONS`)
- **Private**: `_leading_underscore` (e.g., `_internal_method`)

### Import Order

Use isort/ruff import sorting:

```python
# Standard library
import os
from pathlib import Path
from typing import TYPE_CHECKING

# Third-party
import pytest
from langchain_core.language_models import BaseChatModel

# Local imports (relative)
from .agent import AgentConfig
from .events import MyEvent

if TYPE_CHECKING:
    # Type-only imports (avoid circular deps)
    from langchain_core.embeddings import Embeddings
```

---

## Development Workflow

### Daily Workflow

```bash
# 1. Make code changes
vim packages/soothe/src/soothe/sloop/engine/strange_loop.py

# 2. Write/update tests
vim packages/soothe/tests/unit/core/loop/engine/test_strange_loop_model_roles.py

# 3. Run relevant tests
cd packages/soothe
uv run pytest tests/unit/core/loop/engine/test_strange_loop_model_roles.py -v

# 4. Format code
make format

# 5. Check linting
make lint

# 6. Full verification before commit
./scripts/verify_finally.sh
```

### Format and Lint

```bash
# Format all packages
make format

# Check formatting (for CI)
make format-check

# Lint all packages
make lint

# Auto-fix linting issues
make lint-fix
```

### Testing

See **[Testing Guide](testing-guide.md)** for comprehensive testing instructions.

**Quick commands**:
```bash
# Unit tests only
make test-unit

# Integration tests
make test-integration

# Coverage report
make test-coverage
```

### Pre-Commit Hook (Optional)

Install git hook for automatic verification:

```bash
# Create pre-commit hook
echo './scripts/verify_finally.sh' > .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

# Now every commit runs verification automatically
git commit -m "my changes"
```

---

## Pull Request Process

### 1. Create Feature Branch

```bash
# Create branch
git checkout -b feature/my-feature

# Or for bugfix
git checkout -b bugfix/my-bugfix
```

### 2. Make Changes

Follow the daily workflow above.

### 3. Run Verification

**MANDATORY**: Run full verification before pushing:

```bash
./scripts/verify_finally.sh
```

All checks must pass:
- ✅ Workspace integrity
- ✅ Dependency validation
- ✅ Formatting check
- ✅ Linting (zero errors)
- ✅ Unit tests (900+ tests)

### 4. Commit Changes

See [Commit Guidelines](#commit-guidelines) below.

### 5. Push and Create PR

```bash
# Push branch
git push origin feature/my-feature

# Create pull request on GitHub
# Use PR template
```

### PR Template

```markdown
## Summary
Brief description of changes.

## Changes
- Change 1
- Change 2

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests passed
- [ ] Manual testing performed

## Checklist
- [ ] Code formatted (`make format`)
- [ ] Linting passed (`make lint`)
- [ ] Tests passed (`./scripts/verify_finally.sh`)
- [ ] Docstrings updated
- [ ] Implementation guide created (if substantial)
```

### 6. Code Review

- Address reviewer feedback
- Run verification after changes
- Squash commits if requested

### 7. Merge

PR will be merged after:
- ✅ All checks pass
- ✅ Code review approved
- ✅ Documentation updated

---

## Architecture Guidelines

### Module Self-Containment (IG-047)

Place tests **close to the code they test**:

```
packages/soothe/src/soothe/sloop/engine/
├── __init__.py
├── strange_loop.py

packages/soothe/tests/unit/core/loop/engine/
├── test_strange_loop_model_roles.py      # Tests for strange_loop.py
```

### Event Registration

Each module registers its own events:

```python
from soothe.events import register_event
from soothe_sdk.core.events import SootheEvent

class MyCustomEvent(SootheEvent):
    type: str = "soothe.my_module.custom.event"
    data: str

# Register at module load time
register_event(MyCustomEvent, summary_template="Custom: {data}")
```

### Protocol-First Design

Define protocols before implementations:

```python
from typing import Protocol

class MyProtocol(Protocol):
    """Protocol definition."""
    
    def execute(self, goal: str) -> Result:
        """Execute a goal."""
        ...

# Then implement
class MyImplementation:
    """Protocol implementation."""
    
    def execute(self, goal: str) -> Result:
        return Result(status="completed")
```

### No "Layer N" Terminology

Use concrete module names instead:

- ❌ "Layer 1" → ✅ "CoreAgent"
- ❌ "Layer 2" → ✅ "StrangeLoop"
- ❌ "Layer 3" → ✅ "ContextEngine"

Apply to: docstrings, comments, log messages, documentation.

### No Internal Doc References in User-Facing Text

Don't expose IG-XXX or RFC-XXX in user-facing text:

- ❌ `logger.info("[Plan] IG-226 thread continuation")`
- ✅ `logger.info("[Plan] Thread continuation mode enabled")`

**OK in**: Code comments, docstrings (for developer context)
**NOT OK in**: Log messages, user text, CLI output, TUI, events

---

## Commit Guidelines

### Commit Message Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Formatting, missing semicolons, etc.
- `refactor`: Code restructuring
- `test`: Adding tests
- `chore`: Maintenance tasks

### Scopes

Package names or modules:
- `sdk`, `cli`, `core`, `daemon`
- `agent`, `loop`, `memory`, `planner`
- `config`, `events`, `backends`

### Examples

```bash
# Feature
feat(agent): add autonomous goal scheduling

# Bugfix
fix(loop): correct iteration count on timeout

# Documentation
docs(config): update YAML reference with examples

# Refactor
refactor(events): move event registration to modules

# Test
test(loop): add unit tests for timeout retry

# Chore
chore(deps): update langchain to 0.3.0
```

### Commit Body

Explain **why** the change was made:

```
feat(agent): add autonomous goal scheduling

Add RFC-222 AutopilotService for background goal execution.
Enables 24/7 autonomous operation without human intervention.

- AutopilotService manages goal queue
- Worker pool dispatches goals to StrangeLoop
- Context projection for parent→child lineage

Implements: RFC-222
```

---

## Implementation Guides

### When to Create IG

**Substantial work** (multi-step, cross-module, new features):
- Create `docs/impl/NNN-brief-title.md`
- Track scope, decisions, progress

**Minor changes** (bugfixes, single-file, trivial config):
- **Do NOT** create verbose IG
- Use clear commit message + PR description

### IG Naming

- `NNN-brief-title.md` (NNN = sequential number)
- Example: `docs/impl/IG-295-loop-graph-refactor.md`

### IG Template

```markdown
# IG-NNN: Brief Title

**Status**: In Progress | Completed

## Goal
What we're implementing and why.

## Scope
Files and modules affected.

## Approach
Implementation strategy.

## Progress
- [ ] Task 1
- [ ] Task 2
- [ ] Task 3

## Decisions
Key decisions made during implementation.

## References
- RFC-XXX (if applicable)
```

---

## Ecosystem Dependencies

### Check LangChain First

**DO NOT reinvent modules** if langchain ecosystem provides them:

| Feature | Use |
|---------|-----|
| Tools | `langchain.BaseTool` or `@tool` decorator |
| Subagents | `deepagents.SubAgent` or `CompiledSubAgent` |
| MCP | `langchain-mcp-adapters` |
| Skills | `deepagents.SkillsMiddleware` |
| Memory | `deepagents.MemoryMiddleware` |
| Web search | `TavilySearchResults`, `DuckDuckGoSearchRun` |
| ArXiv | `ArxivQueryRun` |
| Wikipedia | `WikipediaQueryRun` |
| Python REPL | `PythonREPLTool` |
| Document loaders | `PyPDFLoader`, `Docx2txtLoader` |
| Model init | `init_chat_model()`, `init_embeddings()` |

**Check**: `langchain-core`, `langchain-community`, `deepagents` first!

---

## Documentation

### Update Documentation

When making changes, update relevant docs:

- **Code changes**: Update docstrings, inline comments
- **API changes**: Update [API Reference](api-reference/index.md)
- **Config changes**: Update [Configuration Guide](configuration-guide/index.md)
- **Architecture changes**: Update [Architecture Overview](architecture/index.md)

### Docstring Standards

- Google-style format
- Args, Returns, Raises sections
- Examples for complex functions
- Keep concise but complete

---

## Release Process

### Versioning

- Semantic versioning: `MAJOR.MINOR.PATCH`
- Version file: `VERSION`
- Package versions in `pyproject.toml`

### Publishing

Publishes **owned** packages only (`soothe`, `soothe-cli`, `soothe-daemon`).
Submodule packages and language clients release from their own repositories.

```bash
# Publish to TestPyPI first
make publish-test

# Then publish to PyPI
make publish

# Or per-package
make cli-publish
make soothe-publish
make daemon-publish
```

---

## Getting Help

### Resources

- **[Architecture Overview](architecture/index.md)** - System design
- **[Testing Guide](testing-guide.md)** - Testing instructions
- **[RFC-000](../specs/RFC-000-system-conceptual-design.md)** - Conceptual design
- **[AGENTS.md](../../AGENTS.md)** - AI agent instructions

### Communication

- GitHub Issues: Bug reports, feature requests
- Pull Requests: Code contributions
- Discussions: Questions, ideas

---

## Summary Checklist

Before submitting PR:

- [ ] Code follows style guidelines
- [ ] Tests added/updated and passing
- [ ] `./scripts/verify_finally.sh` passes
- [ ] Docstrings updated
- [ ] Documentation updated (if needed)
- [ ] Implementation guide created (if substantial)
- [ ] Commit messages follow guidelines
- [ ] PR template filled out

---

## See Also

- **[Testing Guide](testing-guide.md)** - Testing workflow and best practices
- **[Configuration Guide](configuration-guide/index.md)** - Development configuration
- **[Architecture Overview](architecture/index.md)** - System architecture
- **[RFC-000](../specs/RFC-000-system-conceptual-design.md)** - Conceptual design