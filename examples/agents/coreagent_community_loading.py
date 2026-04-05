"""Example: Loading community subagents (Skillify, Weaver) via the plugin system.

This example demonstrates how Soothe core discovers and loads community plugins
through the RFC-600 entry-point discovery mechanism.

Prerequisites:
    pip install -e community/   # installs soothe-community with entry points

Usage:
    python -m examples.agents.coreagent_community_loading
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Demonstrate community plugin loading and subagent resolution."""
    from soothe.config.settings import SootheConfig
    from soothe.core.resolver._resolver_tools import resolve_subagents

    # 1. Create config
    config = SootheConfig()
    logger.info("SootheConfig created")

    # 2. Load plugins (discovers entry points from soothe-community)
    from soothe.plugin.global_registry import is_plugins_loaded, load_plugins

    await load_plugins(config)
    logger.info("Plugins loaded: %s", is_plugins_loaded())

    # 3. Check registry for community subagents
    from soothe.plugin.global_registry import get_plugin_registry

    registry = get_plugin_registry()
    logger.info("Registered subagents: %s", list(registry.list_subagent_names()))

    # 4. Resolve subagents -- community plugins are merged with built-ins
    subagents = resolve_subagents(config, lazy=False)
    subagent_names = [s.get("name") if isinstance(s, dict) else str(s) for s in subagents]
    logger.info("Resolved subagents: %s", subagent_names)

    # 5. Verify community subagents are present
    expected_community = {"skillify", "weaver"}
    found_community = set(subagent_names) & expected_community
    logger.info("Community subagents found: %s", found_community)
    logger.info("Community subagents missing: %s", expected_community - found_community)


if __name__ == "__main__":
    asyncio.run(main())
