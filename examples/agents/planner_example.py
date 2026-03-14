"""Planner subagent example -- runs the planner directly via create_deep_agent.

The planner is a SubAgent (spec dict), so we wrap it in a minimal deep-agent
with a system prompt that forces delegation to the planner subagent.
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).parent.parent))
from _config_helper import load_example_config

from soothe.subagents.planner import create_planner_subagent
from soothe.utils.streaming import run_with_streaming

load_dotenv()

PROJECT_ROOT = str(Path(__file__).parent.parent.parent.resolve())

_SYSTEM_PROMPT = (
    "You are a planning assistant. You MUST use the planner subagent "
    "to create a structured plan for the user's request. Do NOT answer "
    "directly -- always delegate to the planner subagent via the task tool."
)


async def main() -> None:
    from deepagents import create_deep_agent
    from langgraph.checkpoint.memory import MemorySaver

    config = load_example_config()
    planner_spec = create_planner_subagent(model=config.resolve_model("default"))

    agent = create_deep_agent(
        model=config.create_chat_model("default"),
        subagents=[planner_spec],
        system_prompt=_SYSTEM_PROMPT,
        checkpointer=MemorySaver(),
    )

    await run_with_streaming(
        agent,
        [HumanMessage(
            content="Create a plan to add a CLI interface to this project. "
            "The CLI should support commands for running the agent, listing "
            "available subagents, and checking config. Produce a structured plan."
        )],
        show_subagents=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
