#!/usr/bin/env python3
"""Visualize StrangeLoop LangGraph as SVG.

This script:
1. Builds the StrangeLoop graph structure
2. Generates Mermaid diagram syntax
3. Converts Mermaid to SVG using mermaid-cli (if installed)

Usage:
    python scripts/visualize_strange_loop_graph.py

Requirements:
    - mermaid-cli (mmdc) for SVG output: npm install -g @mermaid-js/mermaid-cli

Output:
    - docs/diagrams/strange_loop_graph.mmd  (Mermaid source)
    - docs/diagrams/strange_loop_graph.svg   (SVG diagram)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Ensure soothe package is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "packages/soothe/src"))

from soothe.config import SootheConfig
from soothe.foundation.sloop.orchestrator.builder import build_strange_loop_graph
from soothe.foundation.sloop.orchestrator.runtime_context import LoopRuntimeContext


def create_mock_runtime_context() -> LoopRuntimeContext:
    """Create a minimal mock runtime context for graph building."""
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    config = SootheConfig()

    # Mock required components
    mock_strange_loop = MagicMock()
    mock_strange_loop.config = config
    mock_strange_loop.core_agent = MagicMock()
    mock_strange_loop.loop_planner = MagicMock()
    mock_strange_loop.loop_planner._model = MagicMock()

    mock_state_manager = MagicMock()
    mock_state_manager.loop_id = "test_loop"

    mock_anchor_manager = MagicMock()
    mock_goal_context_manager = MagicMock()
    mock_plan_manager = MagicMock()

    from soothe.foundation.sloop.state.checkpoint import (
        GoalExecutionRecord,
        StrangeLoopCheckpoint,
        ThreadHealthMetrics,
    )

    checkpoint = StrangeLoopCheckpoint(
        loop_id="test_loop",
        thread_ids=["test_thread"],
        current_thread_id="test_thread",
        status="running",
        thread_health_metrics=ThreadHealthMetrics(
            thread_id="test_thread", last_updated=datetime.now(UTC)
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    goal_record = GoalExecutionRecord(
        goal_id="test_goal",
        goal_text="Test goal",
        thread_id="test_thread",
        started_at=datetime.now(UTC),
    )

    from soothe.foundation.sloop.orchestrator.phase_scratch import LoopPhaseScratch
    from soothe.foundation.sloop.state.schemas import LoopState

    state = LoopState(
        goal="Test goal",
        thread_id="test_thread",
        max_iterations=5,
    )

    ctx = LoopRuntimeContext(
        strange_loop=mock_strange_loop,
        state_manager=mock_state_manager,
        anchor_manager=mock_anchor_manager,
        goal_context_manager=mock_goal_context_manager,
        plan_manager=mock_plan_manager,
        checkpoint=checkpoint,
        goal_record=goal_record,
        continue_loop_mode=False,
        recovery_valid_resume=False,
        loop_state=state,
        emit=lambda event_type, data: None,
        scratch=LoopPhaseScratch(),
    )

    return ctx


def get_mermaid_output(graph) -> str:
    """Get Mermaid diagram syntax from LangGraph."""
    return graph.draw_mermaid()


def save_mermaid_file(mermaid: str, output_path: Path) -> None:
    """Save Mermaid syntax to file."""
    # Clean up mermaid output - remove YAML config header for cleaner rendering
    lines = mermaid.split("\n")
    # Skip the YAML config block (--- lines and config)
    start_idx = 0
    for i, line in enumerate(lines):
        if line.strip() == "---":
            if start_idx == 0:
                start_idx = i + 1
            else:
                start_idx = i + 1
                break
        if "graph TD" in line or "graph LR" in line:
            start_idx = i
            break

    clean_mermaid = "\n".join(lines[start_idx:]) if start_idx > 0 else mermaid

    # Add title
    clean_mermaid = f"""---
title: StrangeLoop LangGraph (RFC-220)
config:
  flowchart:
    curve: linear
  theme: base
  themeVariables:
    primaryColor: "#e1f5fe"
    primaryTextColor: "#01579b"
    primaryBorderColor: "#0288d1"
    lineColor: "#0288d1"
    secondaryColor: "#fff3e0"
    tertiaryColor: "#f3e5f5"
---
{clean_mermaid}"""

    output_path.write_text(clean_mermaid)
    print(f"Mermaid source saved to: {output_path}")


def convert_mermaid_to_svg(mermaid_path: Path, svg_path: Path) -> bool:
    """Convert Mermaid file to SVG using mermaid-cli."""
    try:
        result = subprocess.run(
            [
                "mmdc",
                "-i",
                str(mermaid_path),
                "-o",
                str(svg_path),
                "-b",
                "white",
                "--scale",
                "2",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            print(f"SVG diagram saved to: {svg_path}")
            return True
        else:
            print(f"mmdc failed: {result.stderr}")
            return False
    except FileNotFoundError:
        print("mermaid-cli (mmdc) not found.")
        print("Install with: npm install -g @mermaid-js/mermaid-cli")
        return False
    except subprocess.TimeoutExpired:
        print("mmdc timed out")
        return False


def main() -> None:
    """Main entry point."""
    # Output directory
    output_dir = Path(__file__).parent.parent / "docs" / "diagrams"
    output_dir.mkdir(parents=True, exist_ok=True)

    mermaid_path = output_dir / "strange_loop_graph.mmd"
    svg_path = output_dir / "strange_loop_graph.svg"

    print("Building StrangeLoop graph...")

    # Create mock context and build graph
    ctx = create_mock_runtime_context()
    compiled_graph = build_strange_loop_graph(ctx)

    # Get the graph representation
    graph = compiled_graph.get_graph()

    print(f"Graph nodes: {len(graph.nodes)}")
    print(f"Graph edges: {len(graph.edges)}")

    # Generate Mermaid output
    mermaid = get_mermaid_output(graph)

    # Save Mermaid file
    save_mermaid_file(mermaid, mermaid_path)

    # Print Mermaid for reference
    print("\nMermaid diagram syntax:")
    print("-" * 60)
    print(mermaid)
    print("-" * 60)

    # Try to convert to SVG
    success = convert_mermaid_to_svg(mermaid_path, svg_path)

    if not success:
        print("\nTo convert Mermaid to SVG manually:")
        print("  1. Install mermaid-cli: npm install -g @mermaid-js/mermaid-cli")
        print(f"  2. Run: mmdc -i {mermaid_path} -o {svg_path}")
        print("  3. Or use online: https://mermaid.live/")
        print(f"  4. Paste the Mermaid content from: {mermaid_path}")

    # Also generate ASCII version
    print("\nASCII representation:")
    print("-" * 60)
    try:
        ascii_output = graph.draw_ascii()
        print(ascii_output)
    except Exception as e:
        print(f"ASCII generation failed: {e}")
    print("-" * 60)

    # Save node and edge summary
    summary_path = output_dir / "strange_loop_graph_nodes.md"
    summary = "# StrangeLoop LangGraph Node Summary\n\n"
    summary += "## Nodes\n\n"
    for node in graph.nodes:
        # Nodes can be Node objects or strings
        if hasattr(node, "id"):
            summary += f"- `{node.id}`: {node.name or node.id}\n"
        else:
            summary += f"- `{node}`\n"
    summary += "\n## Edges\n\n"
    for edge in graph.edges:
        source = edge.source if hasattr(edge, "source") else str(edge)
        target = edge.target if hasattr(edge, "target") else ""
        conditional = " (conditional)" if hasattr(edge, "data") and edge.data else ""
        if target:
            summary += f"- `{source}` → `{target}`{conditional}\n"

    summary_path.write_text(summary)
    print(f"\nNode summary saved to: {summary_path}")


if __name__ == "__main__":
    main()
