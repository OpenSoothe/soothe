"""CoreAgent with memory example -- Layer 1 runtime with memory protocol.

This example demonstrates CoreAgent WITH memory protocol:
- Memory remember: Storing long-term knowledge across threads
- Memory recall: Retrieving relevant memories semantically
- Memory recall by tags: Filtering by categorical tags
- Memory forget: Removing outdated memories

Use case: Agent with persistent cross-thread memory for long-term knowledge
retention and semantic retrieval.

Run:
    python examples/core_agent/04_with_memory_example.py
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from examples._config_helper import load_example_config
from examples.core_agent._shared.streaming import stream_core_agent

from soothe import create_soothe_agent, MemoryItem

load_dotenv()


async def demonstrate_memory_protocol(agent) -> None:
    """Demonstrate memory protocol capabilities."""
    print("\n[Memory Protocol Demo]")
    print("-" * 40)

    if agent.memory is None:
        print("[Warning] Memory protocol not available (disabled in config)")
        return

    memory = agent.memory

    # 1. Store memory items (cross-thread knowledge)
    print("\n[1] Storing memory items...")
    items = [
        MemoryItem(
            content="The project team prefers using async/await over threading for concurrency.",
            source_thread="team-preferences-thread",
            tags=["team", "preferences", "async", "concurrency"],
            importance=0.8,
        ),
        MemoryItem(
            content="API keys should be stored in .env files and never committed to git.",
            source_thread="security-guidelines-thread",
            tags=["security", "api-keys", "best-practices"],
            importance=0.9,
        ),
        MemoryItem(
            content="The deployment pipeline uses GitHub Actions with staging and production stages.",
            source_thread="deployment-thread",
            tags=["deployment", "ci-cd", "github-actions"],
            importance=0.7,
        ),
        MemoryItem(
            content="Default timeout for API calls is 30 seconds, configurable via SOOTHE_TIMEOUT env.",
            source_thread="config-thread",
            tags=["config", "timeout", "api"],
            importance=0.5,
        ),
    ]

    stored_ids = []
    for item in items:
        item_id = await memory.remember(item)
        stored_ids.append(item_id)
        print(f"  Stored: {item_id[:8]}... - {item.content[:50]}...")

    # 2. Semantic recall
    print("\n[2] Semantic recall...")
    recalled = await memory.recall(
        query="How should I handle API authentication?",
        limit=3,
    )

    print(f"  Found {len(recalled)} relevant memories:")
    for item in recalled:
        print(f"  - [{item.importance:.1f}] {item.content[:60]}...")

    # 3. Tag-based recall
    print("\n[3] Tag-based recall...")
    tag_recalled = await memory.recall_by_tags(
        tags=["security"],
        limit=5,
    )

    print(f"  Found {len(tag_recalled)} memories with tag 'security':")
    for item in tag_recalled:
        print(f"  - {item.content[:60]}...")

    # 4. Update memory
    print("\n[4] Updating memory content...")
    if stored_ids:
        try:
            await memory.update(stored_ids[0], "UPDATED: Team now prefers structured concurrency with task groups.")
            print(f"  Updated: {stored_ids[0][:8]}...")
        except KeyError:
            print("  Update failed: item not found")

    # 5. Forget (remove) a memory
    print("\n[5] Forgetting memory...")
    if len(stored_ids) > 1:
        forgotten = await memory.forget(stored_ids[-1])
        print(f"  Forgotten: {stored_ids[-1][:8]}... - Success: {forgotten}")


async def main() -> None:
    """Run CoreAgent with memory example."""
    print("=" * 60)
    print("Example 04: CoreAgent with Memory Protocol")
    print("=" * 60)

    # Load configuration from config.dev.yml
    config = load_example_config()
    print(f"\n[Config] Model: {config.router.default}")
    print(f"[Config] Memory enabled: {config.protocols.memory.enabled}")

    # Create CoreAgent with memory enabled (from config)
    agent = create_soothe_agent(
        config,
        tools=[],  # No tools for this example
        subagents=[],  # No subagents
    )

    print(f"[Agent] Memory: {type(agent.memory).__name__ if agent.memory else 'None'}")
    print(f"[Agent] Context: {type(agent.context).__name__ if agent.context else 'None'}")
    print(f"[Agent] Policy: {type(agent.policy).__name__ if agent.policy else 'None'}")

    # Demonstrate memory protocol capabilities
    await demonstrate_memory_protocol(agent)

    # Now query the agent - it can use memory for informed responses
    print("\n" + "=" * 40)
    print("Querying with accumulated memory")
    print("=" * 40)

    await stream_core_agent(
        agent,
        "What security best practices should I follow for storing API keys?",
        thread_id="memory-example-thread",
    )

    print("\n" + "=" * 60)
    print("Example completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())