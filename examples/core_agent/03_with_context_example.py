"""CoreAgent with context example -- Layer 1 runtime with context protocol.

This example demonstrates CoreAgent WITH context protocol:
- Context ingestion: Adding knowledge entries to the ledger
- Context projection: Retrieving relevant context for queries
- Thread persistence: Saving/restoring context across sessions

Use case: Agent that accumulates knowledge within a conversation thread
and uses it to inform future responses.

Note: This example requires a working embedding model configuration.
If vector context fails, it will fall back to keyword context.

Run:
    python examples/core_agent/03_with_context_example.py
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from examples._config_helper import load_example_config
from examples.core_agent._shared.streaming import stream_core_agent

from soothe import create_soothe_agent, ContextEntry

load_dotenv()


async def demonstrate_context_protocol(agent) -> None:
    """Demonstrate context protocol capabilities."""
    print("\n[Context Protocol Demo]")
    print("-" * 40)

    if agent.context is None:
        print("[Warning] Context protocol not available (disabled in config)")
        return

    context = agent.context
    context_type = type(context).__name__
    print(f"[Context] Using {context_type} backend")

    # 1. Ingest knowledge entries
    print("\n[1] Ingesting knowledge entries...")
    entries = [
        ContextEntry(
            source="user",
            content="The project uses Python 3.11+ with async/await patterns.",
            tags=["python", "async", "project-info"],
            importance=0.8,
        ),
        ContextEntry(
            source="tool:web_search",
            content="LangGraph is a framework for building stateful, multi-actor applications with LLMs.",
            tags=["langgraph", "framework", "llm"],
            importance=0.7,
        ),
        ContextEntry(
            source="subagent:research",
            content="The system uses a layered architecture: Layer 1 (CoreAgent), Layer 2 (Runner), Layer 3 (GoalEngine).",
            tags=["architecture", "layers", "design"],
            importance=0.9,
        ),
    ]

    for entry in entries:
        try:
            await context.ingest(entry)
            print(f"  Ingested: {entry.source} - {entry.content[:50]}...")
        except Exception as e:
            print(f"  [Warning] Failed to ingest entry: {e}")
            print("  Note: Vector context requires working embedding model. Try keyword backend.")
            return

    # 2. Project context for a query
    print("\n[2] Projecting context for query...")
    try:
        projection = await context.project(
            query="What is the architecture of this system?",
            token_budget=500,
        )

        print(f"  Total entries in ledger: {projection.total_entries}")
        print(f"  Projected entries: {len(projection.entries)}")
        print(f"  Token count: {projection.token_count}")

        for entry in projection.entries:
            print(f"  - [{entry.source}] {entry.content[:60]}...")
    except Exception as e:
        print(f"  [Warning] Projection failed: {e}")

    # 3. Summarize context
    print("\n[3] Summarizing context...")
    try:
        summary = await context.summarize()
        print(f"  Summary: {summary[:200]}...")
    except Exception as e:
        print(f"  [Warning] Summarization failed: {e}")

    # 4. Persist context
    print("\n[4] Persisting context...")
    try:
        await context.persist("demo-thread-context")
        print("  Context persisted to: demo-thread-context")
    except Exception as e:
        print(f"  [Warning] Persist failed: {e}")

    # 5. Restore context
    print("\n[5] Testing context restoration...")
    try:
        restored = await context.restore("demo-thread-context")
        print(f"  Restored: {restored}")
    except Exception as e:
        print(f"  [Warning] Restore failed: {e}")


async def main() -> None:
    """Run CoreAgent with context example."""
    print("=" * 60)
    print("Example 03: CoreAgent with Context Protocol")
    print("=" * 60)

    # Load configuration from config.dev.yml
    config = load_example_config()
    print(f"\n[Config] Model: {config.router.default}")
    print(f"[Config] Context backend: {config.protocols.context.backend}")

    # Override context backend to keyword-json for reliable demo
    # (Vector context requires working embedding model)
    print("[Config] Overriding context backend to keyword-json for demo reliability")
    config.protocols.context.backend = "keyword-json"

    # Create CoreAgent with context enabled (from config)
    agent = create_soothe_agent(
        config,
        tools=[],  # No tools for this example
        subagents=[],  # No subagents
    )

    print(f"[Agent] Context: {type(agent.context).__name__ if agent.context else 'None'}")
    print(f"[Agent] Memory: {agent.memory}")
    print(f"[Agent] Planner: {type(agent.planner).__name__ if agent.planner else 'None'}")

    # Demonstrate context protocol capabilities
    await demonstrate_context_protocol(agent)

    # Now use the agent with context-aware queries
    print("\n" + "=" * 40)
    print("Querying with accumulated context")
    print("=" * 40)

    await stream_core_agent(
        agent,
        "Based on what you know about the system architecture, what layer handles goal management?",
        thread_id="context-example-thread",
    )

    print("\n" + "=" * 60)
    print("Example completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())