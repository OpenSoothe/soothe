"""Nano agent with subagents example.

This example demonstrates a nano agent with configured subagents:
- Subagent configuration from ``config/develop/config.yml``
- Delegation to first-party subagents such as explorer, plan, and research when enabled
- Optional community plugins when installed and configured

Run:
    python packages/soothe-nano/examples/nano_agent/04_nano_with_subagents_example.py
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

_PACKAGES_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PACKAGES_ROOT / "soothe-nano" / "src"))
sys.path.insert(0, str(_PACKAGES_ROOT / "soothe-sdk" / "src"))
sys.path.insert(0, str(_PACKAGES_ROOT / "soothe-deepagents"))

from soothe_nano import create_nano_agent

from _shared.config import load_nano_example_config
from _shared.streaming import stream_nano_agent

load_dotenv()


async def main() -> None:
    """Run nano agent with subagents example."""
    print("=" * 60)
    print("Example 04: Nano Agent with Subagents")
    print("=" * 60)

    config = load_nano_example_config()
    print(f"\n[Config] Model: {config.router.default}")

    print("\n[Config] Subagents from config:")
    for name, subagent_config in config.subagents.items():
        if subagent_config and hasattr(subagent_config, "enabled"):
            status = "enabled" if subagent_config.enabled else "disabled"
            print(f"  - {name}: {status}")

    agent = create_nano_agent(config)

    print(f"\n[Agent] Available subagents: {len(agent.subagents)}")
    for subagent in agent.subagents:
        name = getattr(subagent, "name", "unknown")
        print(f"  - {name}")

    print(f"[Agent] Memory: {type(agent.memory).__name__ if agent.memory else 'None'}")
    print(f"[Agent] Policy: {type(agent.policy).__name__ if agent.policy else 'None'}")

    print("\n" + "=" * 40)
    print("Query 1: Simple task (no delegation needed)")
    print("=" * 40)
    await stream_nano_agent(
        agent,
        "What is the capital of France?",
        thread_id="subagents-example-1",
    )

    print("\n" + "=" * 40)
    print("Query 2: Optional community plugins")
    print("=" * 40)
    print(
        "Skipping optional web automation: install soothe-plugins and enable the matching "
        "subagent entries from that package's documentation."
    )

    print("\n" + "=" * 40)
    print("Query 3: Research task")
    print("=" * 40)
    await stream_nano_agent(
        agent,
        "Search for the latest Python 3.12 features and summarize the key improvements.",
        thread_id="subagents-example-3",
    )

    print("\n" + "=" * 60)
    print("Example completed successfully!")
    print("=" * 60)
    print("\nTip: For optional delegated agents from soothe-plugins, follow that package's README.")


if __name__ == "__main__":
    asyncio.run(main())
