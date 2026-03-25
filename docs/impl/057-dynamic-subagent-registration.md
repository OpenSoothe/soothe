# IG-057: Dynamic Subagent Registration from Plugins

**Status**: 🚧 In Progress
**Created**: 2026-03-25
**RFC**: RFC-0018 (Plugin Extension System)
**Related**: IG-056 (PaperScout Community Plugin)

## Problem

Soothe currently has hardcoded subagent configs:
```python
# src/soothe/config/settings.py
subagents: dict[str, SubagentConfig] = Field(
    default_factory=lambda: {
        "browser": SubagentConfig(),
        "claude": SubagentConfig(),
        "skillify": SubagentConfig(),
        "weaver": SubagentConfig(),
    }
)
```

This prevents third-party plugins from registering their own subagents with custom configs.

## Goal

Enable plugins to dynamically register subagents that:
1. Are discovered via plugin entry_points
2. Can be configured in `config.yml` under `subagents:`
3. Work seamlessly with builtin subagents
4. Require no hardcoded changes to Soothe core

## Architectural Changes

### Change 1: Plugin-to-Subagent Mapping

**Current**: No connection between plugins and subagents

**Proposed**: Plugins can declare subagents via metadata:

```python
@plugin(
    name="paperscout",
    version="1.0.0",
    subagents=["paperscout"],  # NEW: Declare subagents provided
)
class PaperScoutPlugin:
    @subagent(name="paperscout", ...)
    async def create_paperscout(self, model, config, context):
        ...
```

### Change 2: Dynamic Subagent Config Registry

**Add**: `src/soothe/plugin/subagent_registry.py`

```python
class SubagentRegistry:
    """Registry for dynamically discovered subagents."""

    def __init__(self):
        self._factories: dict[str, Callable] = {}
        self._defaults: dict[str, SubagentConfig] = {}

    def register(
        self,
        name: str,
        factory: Callable,
        default_config: SubagentConfig | None = None,
    ):
        """Register a subagent from a plugin."""
        self._factories[name] = factory
        if default_config:
            self._defaults[name] = default_config

    def get_factory(self, name: str) -> Callable | None:
        """Get subagent factory by name."""
        return self._factories.get(name)

    def get_default_config(self, name: str) -> SubagentConfig:
        """Get default config for subagent."""
        return self._defaults.get(name, SubagentConfig())

    def list_all(self) -> list[str]:
        """List all registered subagents."""
        return list(self._factories.keys())
```

### Change 3: Plugin Lifecycle Integration

**Modify**: `src/soothe/plugin/lifecycle.py`

Add subagent registration during plugin load:

```python
async def load_plugin(plugin_class, context):
    """Load a plugin and register its capabilities."""

    # Call on_load hook
    await plugin_instance.on_load(context)

    # Register subagents (NEW)
    if hasattr(plugin_instance, "get_subagents"):
        for subagent_factory in plugin_instance.get_subagents():
            # Extract subagent name from decorator
            name = getattr(subagent_factory, "_subagent_name")

            # Register in global registry
            SUBAGENT_REGISTRY.register(
                name=name,
                factory=subagent_factory,
                default_config=getattr(subagent_factory, "_subagent_config", None),
            )
```

### Change 4: Merge Dynamic and Static Subagents

**Modify**: `src/soothe/config/settings.py`

```python
from soothe.plugin.subagent_registry import SUBAGENT_REGISTRY

class SootheConfig(BaseSettings):
    subagents: dict[str, SubagentConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _merge_subagents(self):
        """Merge builtin and plugin-discovered subagents."""
        # Start with builtin defaults
        builtin = {
            "browser": SubagentConfig(),
            "claude": SubagentConfig(),
            "skillify": SubagentConfig(),
            "weaver": SubagentConfig(),
        }

        # Add plugin-discovered subagents
        for name in SUBAGENT_REGISTRY.list_all():
            if name not in builtin:
                builtin[name] = SUBAGENT_REGISTRY.get_default_config(name)

        # Override with user-provided configs
        for name, config in self.subagents.items():
            builtin[name] = config

        self.subagents = builtin
        return self
```

### Change 5: Resolve Subagents from Registry

**Modify**: `src/soothe/core/agent.py`

```python
def resolve_subagents(config: SootheConfig, ...):
    """Resolve subagents from both builtin and plugin registry."""
    subagents = {}

    # Load builtin subagents
    for name, factory in SUBAGENT_FACTORIES.items():
        if config.subagents.get(name, SubagentConfig()).enabled:
            subagents[name] = factory(...)

    # Load plugin subagents (NEW)
    for name in SUBAGENT_REGISTRY.list_all():
        if name not in subagents:  # Not already loaded as builtin
            if config.subagents.get(name, SubagentConfig()).enabled:
                factory = SUBAGENT_REGISTRY.get_factory(name)
                subagents[name] = factory(...)

    return subagents
```

## Implementation Plan

### Phase 1: Create Subagent Registry

1. Add `src/soothe/plugin/subagent_registry.py`
2. Add `SUBAGENT_REGISTRY` singleton
3. Add `register()`, `get_factory()`, `list_all()` methods
4. Add unit tests

### Phase 2: Modify Plugin Decorator

1. Update `@subagent` decorator in `src/soothe_sdk/decorators/subagent.py`
2. Store metadata: `_subagent_name`, `_subagent_config`
3. Enable plugin to declare subagents in `@plugin` metadata

### Phase 3: Plugin Lifecycle Integration

1. Modify `src/soothe/plugin/lifecycle.py`
2. Register subagents during plugin load
3. Call `SUBAGENT_REGISTRY.register()` for each subagent

### Phase 4: Config System Updates

1. Modify `src/soothe/config/settings.py`
2. Add model_validator to merge dynamic subagents
3. Support user config overrides

### Phase 5: Subagent Resolution Updates

1. Modify `src/soothe/core/agent.py`
2. Check both `SUBAGENT_FACTORIES` and `SUBAGENT_REGISTRY`
3. Merge builtin and plugin subagents

### Phase 6: Create Standalone Package

1. Create `soothe_community/` as separate repo
2. Add `pyproject.toml` with entry_points
3. Move PaperScout to standalone package
4. Test dynamic discovery

## Standalone Package Structure

```
soothe-community/
├── pyproject.toml           # Entry points for soothe.plugins
├── README.md
└── src/
    └── soothe_community/
        ├── __init__.py
        ├── paperscout/
        │   ├── __init__.py  # @plugin, @subagent decorators
        │   ├── events.py
        │   ├── models.py
        │   ├── state.py
        │   ├── nodes.py
        │   ├── reranker.py
        │   ├── email.py
        │   ├── gap_scanner.py
        │   └── implementation.py
        └── (future plugins)/
```

**pyproject.toml**:
```toml
[project.entry-points."soothe.plugins"]
paperscout = "soothe_community.paperscout:PaperScoutPlugin"
```

## Configuration Example

**config.yml**:
```yaml
# Plugin-discovered subagent (no special syntax needed)
subagents:
  paperscout:
    enabled: true
    model: "openai:gpt-4o-mini"
    config:
      arxiv_categories:
        - cs.AI
        - cs.CV
      max_papers: 25
      smtp:
        host: "${SMTP_HOST}"
        user: "${SMTP_USER}"
        password: "${SMTP_PASSWORD}"
      zotero:
        api_key: "${ZOTERO_API_KEY}"
        library_id: "${ZOTERO_LIBRARY_ID}"
```

## Verification

1. Install `soothe-community` package
2. Start Soothe with config containing `paperscout` subagent
3. Verify plugin is discovered via entry_points
4. Verify subagent is registered in `SUBAGENT_REGISTRY`
5. Verify config merges correctly
6. Run: `soothe run "Find papers" --subagent paperscout`

## Success Criteria

- [ ] Plugins can register subagents dynamically
- [ ] User configs work for plugin subagents
- [ ] No hardcoded subagent list in Soothe core
- [ ] Builtin subagents work unchanged
- [ ] Plugin subagents appear in `soothe checkhealth`
- [ ] Full RFC-0018 compliance

## References

- RFC-0018: Plugin Extension System
- IG-056: PaperScout Community Plugin
- Current subagent config: `src/soothe/config/settings.py`
- Current plugin discovery: `src/soothe/plugin/discovery.py`
