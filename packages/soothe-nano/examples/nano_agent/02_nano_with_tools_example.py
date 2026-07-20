"""Nano agent with tools example.

This example demonstrates a nano agent WITH tools:
- Built-in tools from config (execution, file_ops, etc.)
- Custom ad-hoc tools defined inline
- Tool execution and results

Use case: Agent that can execute commands, read files, search web, etc.

Run:
    python packages/soothe-nano/examples/nano_agent/02_nano_with_tools_example.py
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool

_PACKAGES_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PACKAGES_ROOT / "soothe-nano" / "src"))
sys.path.insert(0, str(_PACKAGES_ROOT / "soothe-sdk" / "src"))
sys.path.insert(0, str(_PACKAGES_ROOT / "soothe-deepagents"))

from soothe_nano import create_nano_agent

from _shared.config import load_nano_example_config
from _shared.streaming import stream_nano_agent

load_dotenv()


@tool
def get_current_time() -> str:
    """Get the current date and time."""
    from datetime import datetime

    return datetime.now().isoformat()


@tool
def calculate_sum(numbers: str) -> str:
    """Calculate the sum of a list of numbers."""
    try:
        nums = [float(n.strip()) for n in numbers.split(",")]
        return str(sum(nums))
    except ValueError:
        return "Error: Please provide comma-separated numbers"


async def main() -> None:
    """Run nano agent with tools example."""
    print("=" * 60)
    print("Example 02: Nano Agent with Tools")
    print("=" * 60)

    config = load_nano_example_config()
    print(f"\n[Config] Model: {config.router.default}")
    print(f"[Config] Built-in tools enabled: execution={config.tools.execution.enabled}")

    agent = create_nano_agent(
        config,
        tools=[get_current_time, calculate_sum],
        subagents=[],
    )

    print(f"[Agent] Memory: {agent.memory}")
    print(f"[Agent] Subagents: {len(agent.subagents)}")

    queries = [
        "What is the current time?",
        "Calculate the sum of numbers: 10, 20, 30, 40, 50",
        "Run a simple Python command to print hello world",
    ]

    for i, query in enumerate(queries):
        print(f"\n{'=' * 40}")
        print(f"Query {i + 1}")
        print("=" * 40)
        await stream_nano_agent(
            agent,
            query,
            thread_id=f"tools-example-{i}",
            show_tool_calls=True,
        )

    print("\n" + "=" * 60)
    print("Example completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
