"""Research subagent example -- runs the research CompiledSubAgent directly.

The research subagent is a CompiledSubAgent with its own runnable graph.
We extract the runnable and stream it directly, bypassing the main agent.
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).parent.parent))
from _config_helper import load_example_config

from soothe.subagents.research import create_research_subagent
from soothe.utils.streaming import run_with_streaming

load_dotenv()


async def main() -> None:
    config = load_example_config()
    model = config.create_chat_model("default")

    spec = create_research_subagent(model=model)
    runnable = spec["runnable"]

    await run_with_streaming(
        runnable,
        [HumanMessage(
            content="Research the current state of Rust adoption in 2026."
        )],
        show_subagents=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
