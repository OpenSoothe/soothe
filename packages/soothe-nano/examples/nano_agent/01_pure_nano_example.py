"""Pure nano agent example -- minimal runtime.

This example demonstrates a nano agent with NO protocols:
- No context injection
- No memory recall
- No tools
- No subagents

Just the raw LLM conversation capability.

Use case: Simple chat or Q&A without any external integrations.

Run:
    python packages/soothe-nano/examples/nano_agent/01_pure_nano_example.py
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
    """Run pure nano agent example."""
    print("=" * 60)
    print("Example 01: Pure Nano Agent (Model Only)")
    print("=" * 60)

    config = load_nano_example_config()
    print(f"\n[Config] Model: {config.router.default}")

    agent = create_nano_agent(
        config,
        tools=[],
        subagents=[],
    )

    print(f"[Agent] Memory: {agent.memory}")
    print(f"[Agent] Subagents: {len(agent.subagents)}")

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
