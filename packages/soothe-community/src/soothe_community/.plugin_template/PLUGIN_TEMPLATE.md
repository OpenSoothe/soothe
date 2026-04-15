# Plugin Template

This directory serves as a template for creating new plugins in soothe-community.

## Quick Start

1. Copy this template:
   ```bash
   cp -r src/soothe_community/.plugin_template src/soothe_community/your_plugin
   ```

2. Rename files:
   - `__init__.py.template` → `__init__.py`
   - `events.py.template` → `events.py`
   - `models.py.template` → `models.py`
   - `state.py.template` → `state.py`
   - `implementation.py.template` → `implementation.py`

3. Update content:
   - Replace `your_plugin` with your plugin name
   - Replace `YourPlugin` with your class name
   - Add your dependencies to `pyproject.toml`
   - Register entry point in `pyproject.toml`

4. Add tests in `tests/test_your_plugin/`

5. Update documentation in your plugin's `README.md`

## Template Files

- `__init__.py.template` - Plugin class with decorators
- `events.py.template` - Custom events
- `models.py.template` - Data models
- `state.py.template` - State definitions (for subagents)
- `implementation.py.template` - Core logic
- `README.md.template` - Plugin documentation

## Example: PaperScout Plugin

See `src/soothe_community/paperscout/` for a complete example.