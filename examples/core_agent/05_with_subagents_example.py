"""CoreAgent with subagents example -- Layer 1 runtime with delegation capabilities.

This example demonstrates CoreAgent WITH subagents:
- Subagent configuration from config.dev.yml
- Delegation to Browser subagent for web tasks
- Delegation to Claude subagent for CLI tasks
- Custom ad-hoc subagent creation

Use case: Agent that can delegate specialized tasks to expert subagents
(web browsing, CLI operations, research, etc.)

Run:
    python examples/core_agent/05_with_subagents_example.py
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from examples._config_helper import load_example_config
from examples.core_agent._shared.streaming import stream_core_agent

from soothe import create_soothe_agent

load_dotenv()


async def main() -> None:
    """Run CoreAgent with subagents example."""
    print("=" * 60)
    print("Example 05: CoreAgent with Subagents")
    print("=" * 60)

    # Load configuration from config.dev.yml
    config = load_example_config()
    print(f"\n[Config] Model: {config.router.default}")

    # Print subagent config status
    print("\n[Config] Subagents from config:")
    for name, subagent_config in config.subagents.items():
        if subagent_config and hasattr(subagent_config, "enabled"):
            status = "enabled" if subagent_config.enabled else "disabled"
            print(f"  - {name}: {status}")

    # Create CoreAgent with subagents enabled from config
    # Subagents are automatically loaded based on config.subagents settings
    agent = create_soothe_agent(
        config,
        # Tools are loaded from config by default
        # Subagents are loaded from config by default
    )

    print(f"\n[Agent] Available subagents: {len(agent.subagents)}")
    for subagent in agent.subagents:
        name = getattr(subagent, "name", "unknown")
        print(f"  - {name}")

    print(f"[Agent] Context: {type(agent.context).__name__ if agent.context else 'None'}")
    print(f"[Agent] Memory: {type(agent.memory).__name__ if agent.memory else 'None'}")
    print(f"[Agent] Policy: {type(agent.policy).__name__ if agent.policy else 'None'}")

    # Example queries demonstrating subagent delegation
    # The agent will automatically delegate to appropriate subagents based on task type

    print("\n" + "=" * 40)
    print("Query 1: Simple task (no delegation needed)")
    print("=" * 40)
    await stream_core_agent(
        agent,
        "What is the capital of France?",
        thread_id="subagents-example-1",
    )

    # Note: Web browsing requires browser-use library and proper setup
    # This query may delegate to Browser subagent if enabled
    print("\n" + "=" * 40)
    print("Query 2: Potential browser delegation")
    print("=" * 40)
    print("Note: Browser subagent requires browser-use library and Playwright")
    print("Skipping browser task for this example...")
    # await stream_core_agent(
    #     agent,
    #     "Go to https://news.ycombinator.com and list the top 3 headlines.",
    #     thread_id="subagents-example-2",
    # )

    # Example using research tool (if enabled in config)
    print("\n" + "=" * 40)
    print("Query 3: Research task")
    print("=" * 40)
    await stream_core_agent(
        agent,
        "Search for the latest Python 3.12 features and summarize the key improvements.",
        thread_id="subagents-example-3",
    )

    print("\n" + "=" * 60)
    print("Example completed successfully!")
    print("=" * 60)
    print("\nTip: Enable browser subagent in config.dev.yml for web automation tasks.")
    print("Set subagents.browser.enabled: true and install browser-use library.")


if __name__ == "__main__":
    asyncio.run(main())