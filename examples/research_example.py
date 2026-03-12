"""Research agent example.

Creates a Soothe agent with the research subagent enabled for deep web research.
Streams tool calls, AI text, and research subagent custom progress events.

Requires: `pip install soothe[research]` (langchain-tavily or duckduckgo-search).
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
            "scout": {"enabled": False},
            "research": {"enabled": True},
            "browser": {"enabled": False},
            "claude": {"enabled": False},
        },
    )

    agent = create_soothe_agent(config=config)

    await run_with_streaming(
        agent,
        [HumanMessage(
            content="Research the current state of WebAssembly adoption in 2026. "
        )],
        show_subagents=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
