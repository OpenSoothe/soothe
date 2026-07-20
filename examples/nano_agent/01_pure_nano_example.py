"""Pure nano agent example -- minimal runtime.

This example demonstrates a nano agent with NO protocols:
- No context injection
- No memory recall
- No tools
- No subagents

Just the raw LLM conversation capability.

Use case: Simple chat or Q&A without any external integrations.

Run:
    python examples/nano_agent/01_pure_nano_example.py
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
    """Run pure nano agent example."""
    print("=" * 60)
    print("Example 01: Pure Nano Agent (Model Only)")
    print("=" * 60)

    # Load configuration from config/develop/config.yml
    config = load_example_config()
    print(f"\n[Config] Model: {config.router.default}")

    # Create nano agent with minimal configuration
    # Disable all tools and subagents for pure LLM execution
    agent = create_nano_agent(
        config,
        tools=[],  # No tools
        subagents=[],  # No subagents
    )

    print(f"[Agent] Memory: {agent.memory}")
    print(f"[Agent] Subagents: {len(agent.subagents)}")

    # Example queries demonstrating pure LLM capabilities
    queries = [
        "What is the difference between a list and a tuple in Python?",
        "Explain the concept of middleware in software architecture.",
    ]

    for i, query in enumerate(queries):
        print(f"\n{'=' * 40}")
        print(f"Query {i + 1}")
        print("=" * 40)
        await stream_nano_agent(
            agent,
            query,
            thread_id=f"pure-core-example-{i}",
        )

    print("\n" + "=" * 60)
    print("Example completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
