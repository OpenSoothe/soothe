"""Quick test: Single deep_research query with DashScope config.

This runs a single quick query to verify the deep_research subagent works.
"""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from soothe.foundation.core.agent import create_soothe_agent

from examples._config_helper import load_example_config
from examples.nano_agent._shared.streaming import stream_nano_agent

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Run a single deep_research query."""
    print("=" * 60)
    print("Quick Test: deep_research Subagent")
    print("=" * 60)

    # Load configuration
    config = load_example_config()
    print(f"\n[Config] Model: {config.router.default}")

    # Create CoreAgent with subagents enabled
    agent = create_soothe_agent(config)

    print(f"[Agent] Available subagents: {len(agent.subagents)}")
    for subagent in agent.subagents:
        name = getattr(subagent, "name", "unknown")
        print(f"  - {name}")

    # Single quick research query
    print("\n" + "=" * 60)
    print("Query: Quick comparison research")
    print("=" * 60)
    print("The agent will delegate to deep_research for web-based research.\n")

    await stream_nano_agent(
        agent,
        "What are the main differences between Python 3.12 and Python 3.11? Provide a brief summary.",
        thread_id="deep-research-quick-test",
    )

    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
