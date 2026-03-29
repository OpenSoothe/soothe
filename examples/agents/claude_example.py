"""Claude subagent example -- runs the Claude CompiledSubAgent directly.

The Claude subagent is a CompiledSubAgent with its own runnable graph.
We extract the runnable and stream it directly.
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).parent.parent))

from _shared.streaming import run_with_streaming

from soothe.subagents.claude import create_claude_subagent

load_dotenv()

PROJECT_ROOT = str(Path(__file__).parent.parent.parent.resolve())


async def main() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable is not set.")
        sys.exit(1)

    spec = create_claude_subagent(cwd=PROJECT_ROOT)
    runnable = spec["runnable"]

    await run_with_streaming(
        runnable,
        [
            HumanMessage(
                content="Analyze the src/soothe/ directory and provide a summary of the project "
                "architecture, listing all modules and their responsibilities."
            )
        ],
        show_subagents=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
