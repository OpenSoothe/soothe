"""CoreAgent full composition example -- Layer 1 with all protocols.

This example demonstrates CoreAgent with FULL composition:
- Context protocol: Knowledge accumulation and projection
- Memory protocol: Cross-thread long-term memory
- Tools: Built-in tools from config + custom tools
- Subagents: Delegation to specialized agents

Use case: Full-featured agent capable of:
- Accumulating context within conversations
- Remembering information across sessions
- Executing commands and operations via tools
- Delegating specialized tasks to subagents

Note: This example overrides context backend to keyword-json for reliability.
Vector context requires a working embedding model configuration.

Run:
    python examples/core_agent/06_full_composition_example.py
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from langchain_core.tools import tool

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from examples._config_helper import load_example_config
from examples.core_agent._shared.streaming import stream_core_agent

from soothe import create_soothe_agent, ContextEntry, MemoryItem

load_dotenv()


# Custom ad-hoc tools
@tool
def get_project_status() -> str:
    """Get the current project status and progress.

    Returns:
        JSON string with project status information.
    """
    import json

    status = {
        "phase": "development",
        "progress": "75%",
        "last_updated": datetime.now().isoformat(),
        " blockers": [],
        "team_size": 5,
    }
    return json.dumps(status)


@tool
def log_decision(decision: str, rationale: str) -> str:
    """Log a project decision with its rationale.

    Args:
        decision: The decision made.
        rationale: The reason for the decision.

    Returns:
        Confirmation message.
    """
    return f"Logged decision: '{decision}' with rationale: '{rationale}'"


async def setup_context_and_memory(agent) -> None:
    """Set up initial context and memory for the session."""
    print("\n[Setup] Pre-populating context and memory...")

    # Context: Thread-specific knowledge
    if agent.context:
        context_entries = [
            ContextEntry(
                source="session-setup",
                content="This session is focused on project planning and task coordination.",
                tags=["session", "planning"],
                importance=0.9,
            ),
            ContextEntry(
                source="previous-work",
                content="Previous session completed the API integration module.",
                tags=["progress", "api"],
                importance=0.8,
            ),
            ContextEntry(
                source="team-input",
                content="Team suggested focusing on testing infrastructure next.",
                tags=["team", "testing"],
                importance=0.7,
            ),
        ]
        for entry in context_entries:
            await agent.context.ingest(entry)
        print(f"  Context: {len(context_entries)} entries added")

    # Memory: Cross-thread persistent knowledge
    if agent.memory:
        memory_items = [
            MemoryItem(
                content="The project uses pytest for testing with coverage threshold of 80%.",
                source_thread="setup-thread",
                tags=["testing", "pytest", "coverage"],
                importance=0.85,
            ),
            MemoryItem(
                content="API authentication uses JWT tokens with 24-hour expiry.",
                source_thread="security-thread",
                tags=["security", "api", "jwt"],
                importance=0.9,
            ),
            MemoryItem(
                content="Deployment schedule: staging every Tuesday, production every Friday.",
                source_thread="deployment-thread",
                tags=["deployment", "schedule"],
                importance=0.7,
            ),
        ]
        for item in memory_items:
            await agent.memory.remember(item)
        print(f"  Memory: {len(memory_items)} items stored")


async def demonstrate_full_agent(agent) -> None:
    """Demonstrate full agent capabilities."""
    print("\n" + "=" * 60)
    print("Demonstrating Full Agent Composition")
    print("=" * 60)

    # Query 1: Uses context + memory for informed response
    print("\n[Query 1] Context and Memory-aware planning")
    print("-" * 40)
    await stream_core_agent(
        agent,
        "Based on what we know about the project status and previous work, "
        "what should be our priority for the next sprint?",
        thread_id="full-composition-1",
    )

    # Query 2: Uses tools for action
    print("\n[Query 2] Tool usage for project management")
    print("-" * 40)
    await stream_core_agent(
        agent,
        "Get the current project status and log a decision to focus on testing infrastructure.",
        thread_id="full-composition-2",
    )

    # Query 3: Combines everything
    print("\n[Query 3] Full integration - context + memory + tools")
    print("-" * 40)
    await stream_core_agent(
        agent,
        "Considering our deployment schedule and security requirements, "
        "log a decision about when to deploy the new API changes.",
        thread_id="full-composition-3",
    )

    # Query 4: Research task (uses web search tool if enabled)
    print("\n[Query 4] Research with tool")
    print("-" * 40)
    await stream_core_agent(
        agent,
        "Search for best practices for JWT token refresh strategies and summarize key recommendations.",
        thread_id="full-composition-4",
    )


async def main() -> None:
    """Run CoreAgent full composition example."""
    print("=" * 60)
    print("Example 06: CoreAgent Full Composition")
    print("=" * 60)

    # Load configuration from config.dev.yml
    config = load_example_config()
    print(f"\n[Config] Model: {config.router.default}")
    print(f"[Config] Context backend: {config.protocols.context.backend}")
    print(f"[Config] Memory enabled: {config.protocols.memory.enabled}")
    print(f"[Config] Tools: execution={config.tools.execution.enabled}, web_search={config.tools.web_search.enabled}")

    # Override context backend to keyword-json for reliable demo
    # (Vector context requires working embedding model)
    print("[Config] Overriding context backend to keyword-json for demo reliability")
    config.protocols.context.backend = "keyword-json"

    # Create CoreAgent with full composition
    # Everything is enabled from config by default
    agent = create_soothe_agent(
        config,
        # Add additional custom tools beyond config
        tools=[get_project_status, log_decision],
    )

    # Print agent composition
    print("\n[Agent Composition]")
    print(f"  Context: {type(agent.context).__name__ if agent.context else 'None'}")
    print(f"  Memory: {type(agent.memory).__name__ if agent.memory else 'None'}")
    print(f"  Planner: {type(agent.planner).__name__ if agent.planner else 'None'}")
    print(f"  Policy: {type(agent.policy).__name__ if agent.policy else 'None'}")
    print(f"  Subagents: {len(agent.subagents)}")
    for subagent in agent.subagents:
        name = getattr(subagent, "name", getattr(subagent, "__class__", "unknown"))
        print(f"    - {name}")

    # Set up initial context and memory
    await setup_context_and_memory(agent)

    # Demonstrate full agent capabilities
    await demonstrate_full_agent(agent)

    # Show final context state
    if agent.context:
        print("\n[Final Context State]")
        projection = await agent.context.project("project planning", token_budget=500)
        print(f"  Total entries: {projection.total_entries}")
        print(f"  Projected entries: {len(projection.entries)}")
        summary = await agent.context.summarize()
        print(f"  Summary: {summary[:100]}...")

    # Show final memory state
    if agent.memory:
        print("\n[Final Memory State]")
        recalled = await agent.memory.recall("project testing", limit=3)
        print(f"  Relevant memories for 'project testing': {len(recalled)}")
        for item in recalled:
            print(f"    - [{item.importance:.1f}] {item.content[:50]}...")

    print("\n" + "=" * 60)
    print("Example completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())