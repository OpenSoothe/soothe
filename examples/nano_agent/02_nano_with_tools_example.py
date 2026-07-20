"""Nano agent with tools example.

This example demonstrates a nano agent WITH tools:
- Built-in tools from config (execution, file_ops, etc.)
- Custom ad-hoc tools defined inline
- Tool execution and results

Use case: Agent that can execute commands, read files, search web, etc.

Run:
    python examples/nano_agent/02_nano_with_tools_example.py
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from soothe_nano import create_nano_agent

from examples._config_helper import load_example_config
from examples.nano_agent._shared.streaming import stream_nano_agent

load_dotenv()


# Define custom tools inline
@tool
def get_current_time() -> str:
    """Get the current date and time.

    Returns:
        Current datetime string in ISO format.
    """
    from datetime import datetime

    return datetime.now().isoformat()


@tool
def calculate_sum(numbers: str) -> str:
    """Calculate the sum of a list of numbers.

    Args:
        numbers: Comma-separated list of numbers (e.g., "1,2,3,4,5").

    Returns:
        The sum of the numbers as a string.
    """
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

    # Load configuration from config/develop/config.yml
    config = load_example_config()
    print(f"\n[Config] Model: {config.router.default}")
    print(f"[Config] Built-in tools enabled: execution={config.tools.execution.enabled}")

    # Create nano agent with tools from config + custom tools
    # Tools from config are automatically loaded based on config.tools settings
    agent = create_nano_agent(
        config,
        # Additional custom tools beyond what config provides
        tools=[get_current_time, calculate_sum],
        subagents=[],  # No subagents for this example
    )

    print(f"[Agent] Memory: {agent.memory}")
    print(f"[Agent] Subagents: {len(agent.subagents)}")

    # Example queries demonstrating tool usage
    queries = [
        # Custom tool usage
        "What is the current time?",
        "Calculate the sum of numbers: 10, 20, 30, 40, 50",
        # Built-in execution tool (if enabled in config)
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
