"""Claude agent example.

Creates a Soothe agent with the Claude subagent for code analysis using
the full Claude Code agent capabilities via the Claude Agent SDK.
Streams tool calls, AI text, and Claude subagent custom progress events.

Requires:
  - `pip install soothe[claude]` (claude-agent-sdk)
  - Claude Code CLI installed
  - ANTHROPIC_API_KEY environment variable set
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from soothe import SootheConfig, create_soothe_agent

from soothe.utils._streaming import run_with_streaming

load_dotenv()

PROJECT_ROOT = str(Path(__file__).parent.parent.resolve())


async def main() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable is not set.")
        print("Please set it in your .env file or export it directly.")
        sys.exit(1)

    config = SootheConfig.from_yaml_file("config.dev.yml")
    config.workspace_dir = PROJECT_ROOT
    config.subagents["planner"].enabled = False
    config.subagents["scout"].enabled = False
    config.subagents["research"].enabled = False
    config.subagents["browser"].enabled = False
    config.subagents["claude"].enabled = True
    config.subagents["claude"].config = {"cwd": PROJECT_ROOT}

    agent = create_soothe_agent(config=config)

    await run_with_streaming(
        agent,
        [HumanMessage(
            content="Analyze the src/soothe/ directory and provide a summary of the project "
            "architecture, listing all modules and their responsibilities."
        )],
        show_subagents=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
