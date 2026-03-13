"""Batch tasks example -- tests headless CLI with auto-routing.

Runs a series of diverse tasks sequentially using the Soothe CLI in headless
mode, demonstrating auto-routing to different subagents.

Usage:
    python examples/batch_tasks_example.py
"""

import subprocess
import sys

TASKS = [
    "Create a plan to implement a REST API for user management with authentication.",
    "Research the latest developments in quantum computing error correction in 2026.",
    "Explore the src/soothe/ directory and list all Python modules with their line counts.",
    "Find skills related to natural language processing and text summarization.",
]

TASK_LABELS = [
    "Planning task (auto-routes to planner)",
    "Research task (auto-routes to research)",
    "Code exploration task (auto-routes to scout)",
    "Skill retrieval task (auto-routes to skillify)",
]


def main() -> None:
    print("=" * 60)
    print("Soothe Batch Tasks Example (Headless Mode)")
    print("=" * 60)

    for i, (task, label) in enumerate(zip(TASKS, TASK_LABELS), 1):
        print(f"\n--- Task {i}/{len(TASKS)}: {label} ---")
        print(f"Prompt: {task[:80]}...")
        print()

        result = subprocess.run(
            ["soothe", "run", "--no-tui", task],
            capture_output=False,
            text=True,
        )

        if result.returncode != 0:
            print(f"[WARN] Task {i} exited with code {result.returncode}")

        print(f"\n--- Task {i} complete ---\n")

    print("=" * 60)
    print("All tasks complete.")


if __name__ == "__main__":
    main()
