"""Research agent example -- SOOTHE_HOME aware."""

import asyncio
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
    config = load_example_config()
    config.workspace_dir = PROJECT_ROOT
    config.subagents["planner"].enabled = False
    config.subagents["scout"].enabled = False
    config.subagents["research"].enabled = True
    config.subagents["browser"].enabled = False
    config.subagents["claude"].enabled = False

    agent = create_soothe_agent(config=config)

    await run_with_streaming(
        agent,
        [HumanMessage(
            content="Research the current state of WebAssembly adoption in 2026."
        )],
        show_subagents=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
