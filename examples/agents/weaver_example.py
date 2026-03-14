"""Weaver subagent example -- runs the Weaver CompiledSubAgent directly.

Demonstrates the Weaver subagent for generating task-specific agents from skills.
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).parent.parent))
from _config_helper import load_example_config

from soothe.subagents.weaver import create_weaver_subagent
from soothe.utils.streaming import run_with_streaming

load_dotenv()


async def main() -> None:
    config = load_example_config()

    spec = create_weaver_subagent(
        model=config.create_chat_model("default"),
        config=config,
    )
    runnable = spec["runnable"]

    await run_with_streaming(
        runnable,
        [HumanMessage(
            content="Generate a specialized agent that can perform comprehensive code review "
            "with security analysis, focusing on Python projects."
        )],
        show_subagents=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
