"""Scout subagent example -- runs the scout directly via create_deep_agent.

The scout is a SubAgent (spec dict), so we wrap it in a minimal deep-agent
with a system prompt that forces delegation to the scout subagent.
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).parent.parent))
from _config_helper import load_example_config

from soothe.subagents.scout import create_scout_subagent
from soothe.utils.streaming import run_with_streaming

load_dotenv()

PROJECT_ROOT = str(Path(__file__).parent.parent.parent.resolve())

_SYSTEM_PROMPT = (
    "You are a codebase exploration assistant. You MUST use the scout subagent "
    "to explore the codebase for the user's request. Do NOT answer directly -- "
    "always delegate to the scout subagent via the task tool."
)


async def main() -> None:
    from deepagents import create_deep_agent
    from deepagents.backends.filesystem import FilesystemBackend
    from langgraph.checkpoint.memory import MemorySaver

    config = load_example_config()
    scout_spec = create_scout_subagent(model=config.resolve_model("default"))

    agent = create_deep_agent(
        model=config.create_chat_model("default"),
        subagents=[scout_spec],
        system_prompt=_SYSTEM_PROMPT,
        backend=FilesystemBackend(root_dir=PROJECT_ROOT, virtual_mode=True),
        checkpointer=MemorySaver(),
    )

    await run_with_streaming(
        agent,
        [HumanMessage(
            content="Explore the src/soothe/ directory and summarise the project architecture."
        )],
        show_subagents=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
