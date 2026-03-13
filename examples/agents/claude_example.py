"""Claude agent example -- SOOTHE_HOME aware."""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).parent.parent))
from _config_helper import load_example_config

from soothe import create_soothe_agent
from soothe.utils._streaming import run_with_streaming

load_dotenv()

PROJECT_ROOT = str(Path(__file__).parent.parent.parent.resolve())


async def main() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable is not set.")
        sys.exit(1)

    config = load_example_config()
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
