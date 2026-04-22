"""Browser subagent example -- runs the browser CompiledSubAgent directly.

The browser subagent is a CompiledSubAgent with its own runnable graph.
We extract the runnable and stream it directly.
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).parent.parent))
from _config_helper import load_example_config
from _shared.streaming import run_with_streaming

from soothe.subagents.browser import create_browser_subagent

load_dotenv()


async def main() -> None:
    load_example_config()

    spec = create_browser_subagent(headless=True, max_steps=50)
    runnable = spec["runnable"]

    await run_with_streaming(
        runnable,
        [HumanMessage(content="Go to https://news.ycombinator.com and summarize the top 5 stories.")],
        show_subagents=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
