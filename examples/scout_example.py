"""Scout agent example.

Creates a Soothe agent with the scout subagent for codebase exploration.
Streams tool calls and AI text in real-time.
"""

import asyncio
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from soothe import SootheConfig, create_soothe_agent

from soothe.utils._streaming import run_with_streaming

load_dotenv()

PROJECT_ROOT = str(Path(__file__).parent.parent.resolve())


async def main() -> None:
    config = SootheConfig(
        workspace_dir=PROJECT_ROOT,
        subagents={
            "planner": {"enabled": False},
            "scout": {"enabled": True},
            "research": {"enabled": False},
            "browser": {"enabled": False},
            "claude": {"enabled": False},
        },
    )

    agent = create_soothe_agent(config=config)

    await run_with_streaming(
        agent,
        [HumanMessage(
            content="Explore the src/soothe/ directory and summarise the project architecture."
        )],
    )


if __name__ == "__main__":
    asyncio.run(main())
