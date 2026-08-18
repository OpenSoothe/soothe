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
    - docs/diagrams/strange_loop_stem.mmd   (canonical stem — hand-authored, IG-663)
    - docs/diagrams/strange_loop_graph.mmd  (full-edge Mermaid dump from LangGraph)
    - docs/diagrams/strange_loop_graph.svg   (SVG of full-edge dump)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Ensure soothe package is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "packages/soothe/src"))

# Pre-import to break orchestrator ↔ engine circular import on cold start.
import soothe.config  # noqa: F401
import soothe.sloop.engine.strange_loop  # noqa: F401
from soothe.config import SootheConfig
from soothe.sloop.orchestrator import stations
from soothe.sloop.orchestrator.builder import build_strange_loop_graph
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext


def create_mock_runtime_context() -> LoopRuntimeContext:
    """Create a minimal mock runtime context for graph building."""
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

    from soothe.sloop.state.checkpoint import StrangeLoopCheckpoint, ThreadHealthMetrics
    from soothe.sloop.state.execution_checkpoint import GoalIndexEntry

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
    goal_record = GoalIndexEntry(
        goal_id="test_goal",
        thread_id="test_thread",
        started_at=datetime.now(UTC),
    )

    from soothe.sloop.orchestrator.runtime_context import LoopPhaseScratch
    from soothe.sloop.state.schemas import LoopState

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


# Spine reading order (preprocess → plan → execute → sidecars → complete).
# ``draw_mermaid`` emits nodes/edges alphabetically, which gives dagre a poor
# initial ordering; declaring them in spine order cuts edge crossings.
_STATION_LAYOUT_ORDER: tuple[str, ...] = (
    "__start__",
    stations.INTAKE,
    stations.ENTER_LOOP,
    stations.DELEGATE,
    stations.GATHER_EVIDENCE,
    stations.EVALUATE,
    stations.GENERATE_PLAN,
    stations.COMMIT_PLAN,
    stations.EXECUTE,
    stations.RECORD_PROGRESS,
    stations.CHECK_LIMITS,
    stations.AWAIT_USER,
    stations.FINALIZE,
    "__end__",
)

_MERMAID_HEADER = """---
title: StrangeLoop LangGraph (RFC-220 / RFC-630)
config:
  flowchart:
    curve: basis
    nodeSpacing: 30
    rankSpacing: 40
    useMaxWidth: true
  theme: base
  themeVariables:
    primaryColor: "#e1f5fe"
    primaryTextColor: "#01579b"
    primaryBorderColor: "#0288d1"
    lineColor: "#0288d1"
    secondaryColor: "#fff3e0"
    tertiaryColor: "#f3e5f5"
---
graph TD;
"""


def _strip_frontmatter(mermaid: str) -> str:
    """Drop the YAML config block ``draw_mermaid`` prepends, keeping the graph body."""
    lines = mermaid.splitlines()
    if not lines or lines[0].strip() != "---":
        return mermaid
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :])
    return mermaid


def _layout_rank(node_id: str) -> tuple[int, str]:
    """Sort key placing known stations in spine order, unknown ones last."""
    try:
        return (_STATION_LAYOUT_ORDER.index(node_id), node_id)
    except ValueError:
        return (len(_STATION_LAYOUT_ORDER), node_id)


def save_mermaid_file(mermaid: str, output_path: Path) -> None:
    """Rewrite the ``draw_mermaid`` dump in spine order and save it."""
    node_decls: list[tuple[tuple[int, str], str]] = []
    edge_decls: list[tuple[tuple[int, str], tuple[int, str], str, str, str]] = []
    class_defs: list[str] = []

    for raw in _strip_frontmatter(mermaid).splitlines():
        line = raw.strip()
        if not line or line.startswith(("graph ", "flowchart ")):
            continue
        if line.startswith("classDef"):
            class_defs.append(line)
            continue
        edge = re.match(r"^(\S+?)\s+(-\.->|-->)\s+(\S+?);?$", line)
        if edge:
            source, arrow, target = edge.group(1), edge.group(2), edge.group(3)
            edge_decls.append((_layout_rank(source), _layout_rank(target), source, arrow, target))
            continue
        node = re.match(r"^([A-Za-z_]\w*)", line)
        if node:
            node_decls.append((_layout_rank(node.group(1)), line))

    if not node_decls:
        # Unexpected dump shape — keep the raw body rather than losing the graph.
        output_path.write_text(mermaid)
        print(f"Mermaid source saved verbatim to: {output_path}")
        return

    node_decls.sort(key=lambda item: item[0])
    edge_decls.sort(key=lambda item: (item[0], item[1]))

    body = [f"\t{decl}\n" for _, decl in node_decls]
    body += [f"\t{source} {arrow} {target};\n" for _, _, source, arrow, target in edge_decls]
    body += [f"\t{decl}\n" for decl in class_defs]

    # Abort edges fan in to ``__end__`` from every station; dimming them keeps
    # the spine legible. The happy-path exit (finalize) stays emphasized.
    aborts = [
        index
        for index, (_, _, source, _, target) in enumerate(edge_decls)
        if target == "__end__" and source != stations.FINALIZE
    ]
    if aborts:
        body.append(
            f"\tlinkStyle {','.join(str(i) for i in aborts)} stroke:#b0bec5,stroke-width:1px\n"
        )
    for index, (_, _, source, _, target) in enumerate(edge_decls):
        if source == stations.FINALIZE and target == "__end__":
            body.append(f"\tlinkStyle {index} stroke:#0288d1,stroke-width:2px\n")

    output_path.write_text(_MERMAID_HEADER + "".join(body))
    print(f"Mermaid source saved to: {output_path}")


def convert_mermaid_to_svg(mermaid_path: Path, svg_path: Path) -> bool:
    """Convert Mermaid file to SVG using mermaid-cli (global ``mmdc`` or npx)."""
    env = os.environ.copy()
    # Prefer system Chrome when puppeteer's bundled chrome-headless-shell is
    # unavailable (common in CI / restricted networks).
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if chrome.is_file() and "PUPPETEER_EXECUTABLE_PATH" not in env:
        env["PUPPETEER_EXECUTABLE_PATH"] = str(chrome)

    mmdc_args = ["-i", str(mermaid_path), "-o", str(svg_path), "-b", "white", "--scale", "2"]
    commands = [
        ["mmdc", *mmdc_args],
        ["npx", "--yes", "@mermaid-js/mermaid-cli", *mmdc_args],
    ]

    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            print(f"{command[0]} timed out")
            continue
        if result.returncode == 0:
            stamp_svg_updated(svg_path)
            print(f"SVG diagram saved to: {svg_path}")
            return True
        print(f"{command[0]} failed: {result.stderr.strip()[:400]}")

    print("mermaid-cli unavailable (install: npm install -g @mermaid-js/mermaid-cli)")
    return False


def stamp_svg_updated(svg_path: Path, *, when: datetime | None = None) -> None:
    """Insert or refresh a visible ``Updated:`` stamp under the diagram title."""
    text = svg_path.read_text()
    text = re.sub(
        r'\s*<text[^>]*id="soothe-diagram-updated"[^>]*>.*?</text>',
        "",
        text,
        flags=re.DOTALL,
    )
    stamp_when = when or datetime.now(ZoneInfo("Asia/Shanghai"))
    stamp_label = stamp_when.strftime("%Y-%m-%d %H:%M %Z")

    # Prefer aligning under Mermaid's title text when present.
    title_x = "50%"
    title_match = re.search(
        r'class="flowchartTitleText"[^>]*\bx="([^"]+)"|'
        r'\bx="([^"]+)"[^>]*class="flowchartTitleText"',
        text,
    )
    if title_match:
        title_x = title_match.group(1) or title_match.group(2)

    stamp = (
        f'<text id="soothe-diagram-updated" text-anchor="middle" '
        f'x="{title_x}" y="-6" '
        f'style="font-family:trebuchet ms,verdana,arial,sans-serif;'
        f'font-size:11px;fill:#546e7a">'
        f"Updated: {stamp_label}</text>"
    )
    close = text.rfind("</svg>")
    if close < 0:
        raise ValueError(f"no </svg> in {svg_path}")
    svg_path.write_text(text[:close] + stamp + text[close:])


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

    # Full-edge appendix (do not overwrite hand-authored strange_loop_graph_nodes.md / stem).
    summary_path = output_dir / "strange_loop_graph_edges.md"
    summary = """# StrangeLoop LangGraph — Full Edge Dump

Auto-generated from ``build_strange_loop_graph()``.
Canonical architecture: [`strange_loop_stem.mmd`](strange_loop_stem.mmd) /
[`strange_loop_graph_nodes.md`](strange_loop_graph_nodes.md).
Orchestrator modules: [`orchestrator_modules.md`](orchestrator_modules.md).

Regenerate: ``python scripts/visualize_strange_loop_graph.py``

## Nodes

"""
    for node in graph.nodes:
        if hasattr(node, "id"):
            summary += f"- `{node.id}`: {node.name or node.id}\n"
        else:
            summary += f"- `{node}`\n"
    summary += "\n## All edges\n\n"
    summary += "Solid arrows in Mermaid/SVG are unconditional; dashed are conditional.\n\n"
    for edge in graph.edges:
        source = edge.source if hasattr(edge, "source") else str(edge)
        target = edge.target if hasattr(edge, "target") else ""
        conditional = " (conditional)" if hasattr(edge, "data") and edge.data else ""
        if target:
            summary += f"- `{source}` → `{target}`{conditional}\n"

    summary_path.write_text(summary)
    print(f"\nEdge dump saved to: {summary_path}")


if __name__ == "__main__":
    main()
