"""Example: Using the academic_research subagent for academic literature research.

This example demonstrates how to leverage the academic_research subagent for
iterative academic literature research with adaptive report generation.

The academic_research subagent:
- Searches academic sources (arXiv, Semantic Scholar, etc.)
- Crawls paper URLs for full-text extraction
- Generates structured literature reports with citations
- Supports effort levels: "normal" (default) and "thorough"

Use cases:
- Academic paper research and literature reviews
- Finding citations and related work
- Comparing research methodologies
- State-of-the-art surveys in specific domains

NOT for:
- Local codebase or repository files (use explore/planner instead)
- General web research or news (use deep_research instead)

Prerequisites:
    - Set OPENAI_API_KEY or configure providers in config/develop/config.yml
    - Optional: Set SEMANTIC_SCHOLAR_API_KEY for higher rate limits (https://www.semanticscholar.org/product/api)

Run:
    python -m examples.agents.academic_research_example

Demo mode (no API keys needed):
    DEMO_MODE=1 python -m examples.agents.academic_research_example
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
    # Semantic Scholar API key is optional - the subagent works without it (lower rate limits)
    return has_llm


async def main() -> None:
    """Run academic_research subagent examples."""
    print("=" * 60)
    print("Example: academic_research Subagent")
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
        print("  - Optional: SEMANTIC_SCHOLAR_API_KEY for higher rate limits")
        print("\nAlternatively, run in demo mode:")
        print("  DEMO_MODE=1 python -m examples.agents.academic_research_example")
        print("\nProceeding with limited functionality...\n")

    # Load configuration
    config = load_example_config()
    print(f"\n[Config] Model: {config.router.default}")

    # Verify academic_research is configured
    ar_config = config.subagents.get("academic_research")
    if ar_config and hasattr(ar_config, "enabled"):
        print(f"[Config] academic_research: {'enabled' if ar_config.enabled else 'disabled'}")
        if ar_config.config:
            print(f"[Config]   effort: {ar_config.config.get('effort', 'normal')}")
            print(
                f"[Config]   source_timeout_sec: {ar_config.config.get('source_timeout_sec', 15.0)}"
            )
    else:
        print("[Config] academic_research: using defaults")

    # Create CoreAgent with subagents from config
    # academic_research is a built-in subagent enabled by default
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
        print("  export SEMANTIC_SCHOLAR_API_KEY='your-key'  # Optional, for higher rate limits")
        print("\nExample queries that would be sent to academic_research:")
        print("\n  1. Quick Literature Search:")
        print('     "Find recent papers on transformer attention mechanisms"')
        print("\n  2. Thorough Literature Review (mention 'thorough' for higher effort):")
        print('     "Research the state of the art in RAG systems. Be thorough."')
        print("\n  3. Comparative Methodology Research:")
        print('     "Compare LoRA and QLoRA fine-tuning methods using academic research"')
        print("\n" + "=" * 60)
        print("Demo completed - structure verified!")
        print("=" * 60)
        return

    # Example 1: Quick literature search (normal effort)
    print("\n" + "=" * 60)
    print("Query 1: Quick Literature Search (normal effort)")
    print("=" * 60)
    print("The agent will delegate to academic_research for academic sources.\n")

    await stream_core_agent(
        agent,
        "Find recent papers on transformer attention mechanisms and their computational efficiency. "
        "I'm interested in academic research from arXiv or Semantic Scholar.",
        thread_id="academic-research-example-1",
    )

    # Example 2: Thorough literature review with explicit effort
    print("\n" + "=" * 60)
    print("Query 2: Thorough Literature Review (high effort)")
    print("=" * 60)
    print(
        "Requesting a comprehensive literature review with effort=thorough.\n"
        "Tip: You can mention 'thorough' or 'comprehensive' in your query.\n"
    )

    await stream_core_agent(
        agent,
        "Research the state of the art in retrieval-augmented generation (RAG) systems. "
        "Focus on academic papers from the last 2 years. Cover architectural innovations, "
        "retrieval strategies, and evaluation benchmarks. Be thorough.",
        thread_id="academic-research-example-2",
    )

    # Example 3: Comparative methodology research
    print("\n" + "=" * 60)
    print("Query 3: Comparative Methodology Research")
    print("=" * 60)

    await stream_core_agent(
        agent,
        "Compare LoRA and QLoRA fine-tuning methods for large language models using "
        "academic research. What are the trade-offs in terms of memory efficiency, "
        "performance, and practical deployment?",
        thread_id="academic-research-example-3",
    )

    print("\n" + "=" * 60)
    print("Example completed successfully!")
    print("=" * 60)
    print(
        "\nTips:\n"
        "1. academic_research is ideal for papers and literature reviews\n"
        "2. Use 'thorough' keyword for more comprehensive research\n"
        "3. Reports include citations and source references\n"
        "4. For general web research, use deep_research instead\n"
        "5. For local codebase exploration, use the explore subagent"
    )


if __name__ == "__main__":
    asyncio.run(main())
