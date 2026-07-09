"""Example: Using the deep_research subagent for iterative web research.

This example demonstrates how to leverage the deep_research subagent for
comprehensive public web research with adaptive report generation.

The deep_research subagent:
- Performs iterative web searches with URL crawling
- Gathers diverse sources automatically
- Generates structured, comprehensive reports
- Supports effort levels: "normal" (default) and "thorough"

Use cases:
- External fact gathering and comparisons
- Industry landscape research
- How-to guides and tutorials from the web
- Current events and news analysis

NOT for:
- Local codebase or repository files (use explore/planner instead)
- Academic literature (use academic_research instead)

Prerequisites:
    - Set OPENAI_API_KEY or configure providers in config/develop/config.yml
    - Set TAVILY_API_KEY for web search (get from https://tavily.com)

Run:
    python -m examples.agents.deep_research_example

Demo mode (no API keys needed):
    DEMO_MODE=1 python -m examples.agents.deep_research_example
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from soothe.foundation.core.agent import create_soothe_agent

from examples._config_helper import load_example_config
from examples.core_agent._shared.streaming import stream_core_agent

load_dotenv()

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Demo mode flag - set DEMO_MODE=1 to run without API keys
DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")


def check_api_keys() -> bool:
    """Check if required API keys are configured."""
    has_llm = bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("DASHSCOPE_API_KEY"))
    has_search = bool(os.environ.get("TAVILY_API_KEY"))
    return has_llm and has_search


async def main() -> None:
    """Run deep_research subagent example."""
    print("=" * 60)
    print("Example: deep_research Subagent")
    print("=" * 60)

    # Check API keys
    if DEMO_MODE:
        print("\n[Demo Mode] Running without API keys - showing structure only")
    elif not check_api_keys():
        print("\n" + "!" * 60)
        print("WARNING: Missing required API keys")
        print("!" * 60)
        print("\nTo run this example with live queries, set these environment variables:")
        print("  - OPENAI_API_KEY (or DASHSCOPE_API_KEY for alternative provider)")
        print("  - TAVILY_API_KEY (get from https://tavily.com)")
        print("\nAlternatively, run in demo mode:")
        print("  DEMO_MODE=1 python -m examples.agents.deep_research_example")
        print("\nProceeding with limited functionality...\n")

    # Load configuration
    config = load_example_config()
    print(f"\n[Config] Model: {config.router.default}")

    # Verify deep_research is configured
    dr_config = config.subagents.get("deep_research")
    if dr_config and hasattr(dr_config, "enabled"):
        print(f"[Config] deep_research: {'enabled' if dr_config.enabled else 'disabled'}")
        if dr_config.config:
            print(f"[Config]   effort: {dr_config.config.get('effort', 'normal')}")
            print(
                f"[Config]   source_timeout_sec: {dr_config.config.get('source_timeout_sec', 10.0)}"
            )
    else:
        print("[Config] deep_research: using defaults")

    # Create CoreAgent with subagents enabled
    agent = create_soothe_agent(config)

    print(f"\n[Agent] Available subagents: {len(agent.subagents)}")
    for subagent in agent.subagents:
        name = getattr(subagent, "name", "unknown")
        print(f"  - {name}")

    # Demo mode or missing keys: show structure only
    if DEMO_MODE or not check_api_keys():
        print("\n" + "-" * 60)
        print("Demo Mode: Skipping live queries")
        print("-" * 60)
        print("\nTo run live queries, set these environment variables:")
        print("  export OPENAI_API_KEY='your-key'")
        print("  export TAVILY_API_KEY='your-key'")
        print("\nExample queries that would be sent to deep_research:")
        print("\n  1. Quick Research:")
        print('     "What are the key features of Python 3.12 vs Python 3.11?"')
        print("\n  2. Thorough Research (mention 'thorough' for higher effort):")
        print(
            '     "Research AI agent frameworks in 2024-2025. Compare LangGraph, AutoGen, CrewAI. Be thorough."'
        )
        print("\n" + "=" * 60)
        print("Demo completed - structure verified!")
        print("=" * 60)
        return

    # Example 1: Quick research query
    print("\n" + "=" * 60)
    print("Query 1: Quick Research (normal effort)")
    print("=" * 60)
    print("The agent will delegate to deep_research for web-based research.\n")

    await stream_core_agent(
        agent,
        "What are the key features of Python 3.12 and how do they compare to Python 3.11?",
        thread_id="deep-research-example-1",
    )

    # Example 2: Thorough research with explicit effort level
    print("\n" + "=" * 60)
    print("Query 2: Thorough Research (high effort)")
    print("=" * 60)
    print(
        "Requesting a more comprehensive research with effort=thorough.\n"
        "Tip: You can mention 'thorough' or 'comprehensive' in your query, "
        "or use the effort parameter when calling the task tool directly.\n"
    )

    await stream_core_agent(
        agent,
        "Research the current state of AI agent frameworks in 2024-2025. "
        "Compare LangGraph, AutoGen, CrewAI, and similar frameworks. "
        "Focus on architecture patterns, tool integration, and multi-agent coordination. "
        "Be thorough.",
        thread_id="deep-research-example-2",
    )

    print("\n" + "=" * 60)
    print("Example completed successfully!")
    print("=" * 60)
    print(
        "\nTips:\n"
        "1. deep_research is ideal for external web research\n"
        "2. Use 'thorough' keyword for more comprehensive reports\n"
        "3. Reports include source references and citations\n"
        "4. For academic papers, consider using academic_research instead\n"
        "5. For local codebase exploration, use the explore subagent"
    )


if __name__ == "__main__":
    asyncio.run(main())
