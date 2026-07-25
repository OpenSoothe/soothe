"""StrangeLoop (non-autopilot) example via SootheRunner.

This is the host-level counterpart to fj-ai's nano one-shot CLI:

- Loads ``~/.soothe/config/nano.yml`` (+ optional ``soothe.yml`` overlay)
- Forces SQLite persistence for standalone use
- Runs the interactive StrangeLoop path (``autopilot_job`` is not set)

Unlike ``create_nano_agent`` / fj-ai, this goes through ``SootheRunner``:
intent classification, planning, step execution, and ``soothe.*`` events.

Requires a working model config (``OPENAI_API_KEY`` / ``ANTHROPIC_API_KEY`` /
provider keys in ``nano.yml``).

Run from the monorepo root::

    uv run python examples/01_strange_loop_example.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make local ``_shared`` importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _shared.config import load_soothe_example_config
from _shared.streaming import stream_soothe_runner
from soothe.runner import SootheRunner, generate_thread_id


async def main() -> None:
    """Run a short StrangeLoop query and print the stream."""
    print("=" * 60)
    print("Example 01: StrangeLoop via SootheRunner (non-autopilot)")
    print("=" * 60)

    config = load_soothe_example_config()
    print(f"\n[Config] Model: {config.router.default}")
    print(f"[Config] Persistence: {config.persistence.default_backend}")
    print(f"[Config] Autopilot: {config.agent.autopilot.enabled}")
    print(f"[Config] Loop enabled: {config.agent.loop.enabled}")

    runner = SootheRunner(config)
    thread_id = generate_thread_id()
    workspace = str(Path.cwd().resolve())

    print(f"[Runner] thread_id={thread_id}")
    print(f"[Runner] workspace={workspace}")

    try:
        await stream_soothe_runner(
            runner,
            "List the Python packages under packages/ and summarize what each owns "
            "in one short sentence. Prefer reading the repo layout over guessing.",
            thread_id=thread_id,
            workspace=workspace,
        )
    finally:
        await runner.cleanup()

    print("\n" + "=" * 60)
    print("Example completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
