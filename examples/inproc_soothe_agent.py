"""In-process Soothe agent example -- embed Soothe as a library dependency.

This example demonstrates how to use Soothe as an embedded library:
- Import and configure SootheConfig programmatically
- Create CoreAgent via create_soothe_agent()
- Stream execution in-process without daemon
- Add custom tools for domain-specific functionality

Use case: Embedding Soothe agent capabilities into your own Python application
without running a separate daemon process.

Prerequisites:
    pip install soothe  # or use local development install

Environment:
    Set OPENAI_API_KEY or configure providers in config file.

Run:
    python examples/inproc_soothe_agent.py
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool

# For installed package: from soothe.core import create_soothe_agent; from soothe.config.settings import SootheConfig
# For local dev: add path and import
sys.path.insert(0, str(Path(__file__).parent.parent))
from soothe.config import SootheConfig
from soothe.core import create_soothe_agent

load_dotenv()


# Define domain-specific custom tools
@tool
def get_system_info() -> str:
    """Get basic system information.

    Returns:
        JSON string with platform, python version, and working directory.
    """
    import json
    import platform

    return json.dumps(
        {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "working_dir": str(Path.cwd()),
        }
    )


@tool
def read_file_safe(path: str) -> str:
    """Safely read a file with size limits.

    Args:
        path: File path to read (relative to workspace).

    Returns:
        File contents (truncated to 500 chars) or error message.
    """
    try:
        file_path = Path(path)
        if not file_path.exists():
            return f"File not found: {path}"
        content = file_path.read_text()
        if len(content) > 500:
            content = content[:500] + "... (truncated)"
        return content
    except Exception as e:
        return f"Error reading file: {e}"


async def stream_agent_response(
    agent,
    query: str,
    thread_id: str = "inproc-demo",
) -> str:
    """Stream agent response with formatted output.

    Args:
        agent: CoreAgent instance.
        query: User query string.
        thread_id: Thread identifier.

    Returns:
        Final AI response text.
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    print(f"\n[User] {query}\n")
    print("[Agent] ", end="", flush=True)

    messages = [HumanMessage(content=query)]
    config = {"configurable": {"thread_id": thread_id}}

    final_response = ""

    async for chunk in agent.astream(
        {"messages": messages},
        config=config,
        stream_mode=["messages", "updates"],
        subgraphs=True,
    ):
        if not isinstance(chunk, tuple) or len(chunk) != 3:
            continue

        namespace, mode, data = chunk

        if mode == "messages":
            if not isinstance(data, tuple) or len(data) != 2:
                continue
            message_obj, metadata = data

            if isinstance(message_obj, AIMessage):
                # Stream AI content
                if isinstance(message_obj.content, str) and message_obj.content:
                    print(message_obj.content, end="", flush=True)
                    final_response = message_obj.content

                # Show tool calls
                if hasattr(message_obj, "tool_calls") and message_obj.tool_calls:
                    for tc in message_obj.tool_calls:
                        if isinstance(tc, dict):
                            print(f"\n[Tool: {tc.get('name', '?')}]", end=" ", flush=True)

            elif isinstance(message_obj, ToolMessage):
                # Show tool result preview
                preview = str(message_obj.content)[:80]
                print(f"→ {preview}...", end=" ", flush=True)

    print("\n")
    return final_response


async def main() -> None:
    """Run in-process Soothe agent demonstration."""
    print("=" * 60)
    print("In-Process Soothe Agent Example")
    print("=" * 60)

    # Option 1: Use default config (relies on OPENAI_API_KEY env var)
    # config = SootheConfig()

    # Option 2: Load from YAML file
    config_path = Path(__file__).parent.parent / "config" / "config.dev.yml"
    if config_path.exists():
        config = SootheConfig.from_yaml_file(str(config_path))
        print(f"[Config] Loaded from: {config_path}")
    else:
        config = SootheConfig()
        print("[Config] Using defaults (requires OPENAI_API_KEY)")

    print(f"[Config] Model: {config.router.default}")
    print(f"[Config] Workspace: {config.workspace_dir}")

    # Create in-process agent with custom tools
    print("\n[Init] Creating CoreAgent...")
    agent = create_soothe_agent(
        config,
        tools=[get_system_info, read_file_safe],
        subagents=[],  # No subagents for minimal footprint
    )

    print(f"[Agent] Memory protocol: {type(agent.memory).__name__ if agent.memory else 'None'}")
    print(f"[Agent] Planner protocol: {type(agent.planner).__name__ if agent.planner else 'None'}")
    print(f"[Agent] Policy protocol: {type(agent.policy).__name__ if agent.policy else 'None'}")
    print("[Agent] Custom tools: 2")

    # Demonstrate agent capabilities
    queries = [
        "What is the current system environment?",
        "Read the README file and summarize it briefly",
        "Calculate what 15 * 7 + 23 equals",
    ]

    for i, query in enumerate(queries):
        print(f"\n{'─' * 40}")
        print(f"Turn {i + 1}")
        print("─" * 40)
        await stream_agent_response(agent, query, thread_id=f"inproc-turn-{i}")

    print("\n" + "=" * 60)
    print("In-process agent completed successfully!")
    print("=" * 60)
    print("\nKey takeaways:")
    print("- Soothe can be embedded as a library dependency")
    print("- create_soothe_agent() returns CoreAgent for direct execution")
    print("- Custom tools extend agent capabilities for your domain")
    print("- Streaming provides real-time response rendering")
    print("- No daemon process needed for in-process integration")


if __name__ == "__main__":
    asyncio.run(main())
