"""Skillify subagent example -- runs the Skillify CompiledSubAgent directly.

Demonstrates the Skillify subagent for semantic skill indexing and retrieval.
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).parent.parent))
from _config_helper import load_example_config

from soothe.subagents.skillify import create_skillify_subagent
from soothe.utils.streaming import run_with_streaming

load_dotenv()


async def main() -> None:
    config = load_example_config()

    spec = create_skillify_subagent(
        model=config.create_chat_model("default"),
        config=config,
    )
    runnable = spec["runnable"]

    await run_with_streaming(
        runnable,
        [HumanMessage(
            content="Find skills related to web scraping, data extraction, and API integration."
        )],
        show_subagents=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
