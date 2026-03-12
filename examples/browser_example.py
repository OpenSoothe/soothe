"""Browser agent example.

Creates a Soothe agent with the browser subagent for web automation.
The browser subagent uses the browser-use library with its own LLM loop.
Streams tool calls, AI text, and browser subagent custom progress events.

Privacy-first defaults:
- Browser extensions (uBlock Origin, cookie handler, ClearURLs) are disabled
- Cloud service connections (api.browser-use.com) are disabled
- Anonymous telemetry (PostHog) is disabled

To re-enable these features, pass parameters to the subagent config:
    config = SootheConfig(
        subagents={
            "browser": {
                "enabled": True,
                "disable_extensions": False,
                "disable_cloud": False,
                "disable_telemetry": False,
            }
        }
    )

Requires: `pip install soothe[browser]` (browser-use).
"""

import asyncio

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from soothe import SootheConfig, create_soothe_agent

from soothe.utils._streaming import run_with_streaming

load_dotenv()


async def main() -> None:
    config = SootheConfig(
        subagents={
            "planner": {"enabled": False},
            "scout": {"enabled": False},
            "research": {"enabled": False},
            "browser": {"enabled": True},
            "claude": {"enabled": False},
        },
    )

    agent = create_soothe_agent(config=config)

    await run_with_streaming(
        agent,
        [HumanMessage(
            content="从雪球https://xueqiu.com/获取文远知行的年报信息"
        )],
        show_subagents=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
