"""Nano agent with subagents example.

This example demonstrates a nano agent with configured subagents:
- Subagent configuration from config/develop/config.yml
- Delegation to first-party subagents such as explorer, plan, and research when enabled
- Optional community plugins when installed and configured

Use case: Agent that can delegate specialized tasks to expert subagents
(filesystem search, planning, research, etc.)

Run:
    python examples/nano_agent/04_nano_with_subagents_example.py
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from soothe_nano import create_nano_agent

from examples._config_helper import load_example_config
from examples.nano_agent._shared.streaming import stream_nano_agent

load_dotenv()


async def main() -> None:
    """Run nano agent with subagents example."""
    print("=" * 60)
    print("Example 04: Nano Agent with Subagents")
    print("=" * 60)

    # Load configuration from config/develop/config.yml
    config = load_example_config()
    print(f"\n[Config] Model: {config.router.default}")

    # Print subagent config status
    print("\n[Config] Subagents from config:")
    for name, subagent_config in config.subagents.items():
        if subagent_config and hasattr(subagent_config, "enabled"):
            status = "enabled" if subagent_config.enabled else "disabled"
            print(f"  - {name}: {status}")

    # Create nano agent with subagents enabled from config
    # Subagents are automatically loaded based on config.subagents settings
    agent = create_nano_agent(
        config,
        # Tools are loaded from config by default
        # Subagents are loaded from config by default
    )

    print(f"\n[Agent] Available subagents: {len(agent.subagents)}")
    for subagent in agent.subagents:
        name = getattr(subagent, "name", "unknown")
        print(f"  - {name}")

    print(f"[Agent] Memory: {type(agent.memory).__name__ if agent.memory else 'None'}")
    print(f"[Agent] Policy: {type(agent.policy).__name__ if agent.policy else 'None'}")

    # Example queries demonstrating subagent delegation
    # The agent will automatically delegate to appropriate subagents based on task type

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
        "subagent entries from that package’s documentation."
    )

    # Example using research tool (if enabled in config)
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
    print("\nTip: For optional delegated agents from soothe-plugins, follow that package’s README.")


if __name__ == "__main__":
    asyncio.run(main())
