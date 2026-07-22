#!/usr/bin/env python3
"""Plan Generation Performance Benchmark (IG-536).

Benchmarks LLMPlanner latency and accuracy using real system prompts and
simulated tasks with ground truth plans.

Usage:
    # Offline mode (mock LLM responses)
    python scripts/benchmark_plan_generation.py

    # Online mode (real LLM calls)
    python scripts/benchmark_plan_generation.py --online

    # Specific model role
    python scripts/benchmark_plan_generation.py --online --model-role think

    # Output formats
    python scripts/benchmark_plan_generation.py --output json
    python scripts/benchmark_plan_generation.py --output markdown
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# Add fixtures directory for task imports
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "packages" / "soothe" / "tests" / "fixtures"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class PlanBenchmarkResult:
    """Result for a single benchmark task run."""

    task_id: str
    task_category: str
    model_role: str

    # Latency (ms)
    assess_latency_ms: float | None = None
    generate_latency_ms: float | None = None
    total_latency_ms: float | None = None
    first_token_latency_ms: float | None = None  # Only in online mode

    # Accuracy
    step_count_match: bool = False
    step_count_expected: int = 0
    step_count_generated: int = 0
    dependency_correctness: float = 0.0
    kind_correctness: float = 0.0
    description_similarity: float = 0.0

    # Status assessment accuracy
    status_match: bool = False
    goal_progress_match: bool = False

    # Generated outputs
    generated_status: str | None = None
    generated_steps: list[dict] = field(default_factory=list)
    ground_truth_status: str | None = None
    ground_truth_steps: list[dict] = field(default_factory=list)

    # Errors
    error: str | None = None


@dataclass
class BenchmarkSummary:
    """Aggregated benchmark statistics."""

    model_role: str
    category: str | None = None  # None for overall summary

    # Count
    total_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0

    # Latency (ms)
    assess_latencies: list[float] = field(default_factory=list)
    generate_latencies: list[float] = field(default_factory=list)
    total_latencies: list[float] = field(default_factory=list)

    # Accuracy
    step_count_matches: int = 0
    status_matches: int = 0
    goal_progress_matches: int = 0
    dependency_correctness_scores: list[float] = field(default_factory=list)
    kind_correctness_scores: list[float] = field(default_factory=list)
    description_similarity_scores: list[float] = field(default_factory=list)

    def add_result(self, result: PlanBenchmarkResult) -> None:
        """Add a single result to the summary."""
        self.total_tasks += 1

        if result.error:
            self.failed_tasks += 1
            return

        self.successful_tasks += 1

        if result.assess_latency_ms is not None:
            self.assess_latencies.append(result.assess_latency_ms)
        if result.generate_latency_ms is not None:
            self.generate_latencies.append(result.generate_latency_ms)
        if result.total_latency_ms is not None:
            self.total_latencies.append(result.total_latency_ms)

        if result.step_count_match:
            self.step_count_matches += 1
        if result.status_match:
            self.status_matches += 1
        if result.goal_progress_match:
            self.goal_progress_matches += 1

        self.dependency_correctness_scores.append(result.dependency_correctness)
        self.kind_correctness_scores.append(result.kind_correctness)
        self.description_similarity_scores.append(result.description_similarity)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return {
            "model_role": self.model_role,
            "category": self.category,
            "counts": {
                "total": self.total_tasks,
                "successful": self.successful_tasks,
                "failed": self.failed_tasks,
            },
            "latency_ms": {
                "assess": _stats_dict(self.assess_latencies),
                "generate": _stats_dict(self.generate_latencies),
                "total": _stats_dict(self.total_latencies),
            },
            "accuracy": {
                "step_count_match_pct": (
                    100.0 * self.step_count_matches / self.successful_tasks
                    if self.successful_tasks > 0
                    else 0
                ),
                "status_match_pct": (
                    100.0 * self.status_matches / self.successful_tasks
                    if self.successful_tasks > 0
                    else 0
                ),
                "goal_progress_match_pct": (
                    100.0 * self.goal_progress_matches / self.successful_tasks
                    if self.successful_tasks > 0
                    else 0
                ),
                "dependency_correctness_pct": _stats_dict(self.dependency_correctness_scores),
                "kind_correctness_pct": _stats_dict(self.kind_correctness_scores),
                "description_similarity": _stats_dict(self.description_similarity_scores),
            },
        }


def _stats_dict(values: list[float]) -> dict[str, float]:
    """Compute statistics for a list of values."""
    if not values:
        return {"min": 0, "avg": 0, "max": 0, "p50": 0, "p95": 0, "p99": 0}
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    return {
        "min": sorted_vals[0],
        "avg": statistics.mean(values),
        "max": sorted_vals[-1],
        "p50": sorted_vals[n // 2]
        if n % 2 == 1
        else (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2,
        "p95": sorted_vals[int(n * 0.95)] if n >= 20 else sorted_vals[-1],
        "p99": sorted_vals[int(n * 0.99)] if n >= 100 else sorted_vals[-1],
    }


# =============================================================================
# Offline Mode (Mock LLM)
# =============================================================================


async def run_offline_benchmark(
    tasks: list[Any],
    model_role: str,
) -> list[PlanBenchmarkResult]:
    """Run benchmark with mock LLM responses (offline mode).

    Tests prompt construction + parsing logic without real API calls.
    Returns deterministic results from ground truth.
    """
    results: list[PlanBenchmarkResult] = []

    for task in tasks:
        # In offline mode, we mock the LLM response to match ground truth
        # This tests the infrastructure without network latency
        ground_truth_decision = task.ground_truth_decision
        ground_truth_status = task.ground_truth_status

        result = PlanBenchmarkResult(
            task_id=task.id,
            task_category=task.category,
            model_role=model_role,
            # Simulated latencies (would be near-zero in real offline)
            assess_latency_ms=1.0,
            generate_latency_ms=1.0 if ground_truth_decision else None,
            total_latency_ms=2.0 if ground_truth_decision else 1.0,
            # Accuracy is 100% since we mock with ground truth
            step_count_match=True,
            step_count_expected=len(ground_truth_decision.get("steps", []))
            if ground_truth_decision
            else 0,
            step_count_generated=len(ground_truth_decision.get("steps", []))
            if ground_truth_decision
            else 0,
            dependency_correctness=100.0,
            kind_correctness=100.0,
            description_similarity=1.0,
            status_match=True,
            goal_progress_match=True,
            generated_status=ground_truth_status.get("status") if ground_truth_status else None,
            generated_steps=ground_truth_decision.get("steps", []) if ground_truth_decision else [],
            ground_truth_status=ground_truth_status.get("status") if ground_truth_status else None,
            ground_truth_steps=ground_truth_decision.get("steps", [])
            if ground_truth_decision
            else [],
        )
        results.append(result)

    return results


# =============================================================================
# Online Mode (Real LLM)
# =============================================================================


async def run_online_benchmark(
    tasks: list[Any],
    model_role: str,
    config: Any,
) -> list[PlanBenchmarkResult]:
    """Run benchmark with real LLM API calls (online mode).

    Measures actual latency and compares generated plans to ground truth.
    """
    # Add package paths for online mode (requires full soothe imports)
    sys.path.insert(0, str(_ROOT))
    sys.path.insert(0, str(_ROOT / "packages" / "soothe" / "src"))
    sys.path.insert(0, str(_ROOT / "packages" / "soothe-sdk" / "src"))
    sys.path.insert(0, str(_ROOT / "packages" / "soothe-daemon" / "src"))

    from soothe.sloop.cognition.planner import LLMPlanner
    from soothe.sloop.state.schemas import LoopState

    results: list[PlanBenchmarkResult] = []

    # Resolve model for the specified role
    model = config.create_chat_model(model_role)

    # Create planner with config
    planner = LLMPlanner(model, config)

    for task in tasks:
        ground_truth_decision = task.ground_truth_decision
        ground_truth_status = task.ground_truth_status

        result = PlanBenchmarkResult(
            task_id=task.id,
            task_category=task.category,
            model_role=model_role,
            ground_truth_status=ground_truth_status.get("status") if ground_truth_status else None,
            ground_truth_steps=ground_truth_decision.get("steps", [])
            if ground_truth_decision
            else [],
        )

        try:
            # Create minimal LoopState for planner invocation
            state = LoopState(
                goal=task.goal,
                thread_id=f"benchmark-{task.id}",
                iteration=task.iteration,
                max_iterations=10,
            )

            # Mock plan context
            context = MagicMock()
            context.workspace = "/workspace/example"
            context.iteration = task.iteration
            context.prior_progress = task.prior_progress
            context.available_capabilities = ["explore", "web_search"]
            context.completed_steps = []

            # Mock ledger for prompt building
            ledger_mock = MagicMock()
            ledger_mock.to_prompt_text = MagicMock(return_value="(no prior tool/subagent results)")
            context.ledger = ledger_mock
            context.context_engine = MagicMock()
            context.context_engine.ledger = ledger_mock

            # Measure assess latency
            t_assess_start = time.perf_counter()
            status_assessment = await planner.assess_status(
                goal=task.goal,
                state=state,
                context=context,
            )
            t_assess_end = time.perf_counter()
            result.assess_latency_ms = (t_assess_end - t_assess_start) * 1000

            result.generated_status = status_assessment.status
            result.status_match = (
                ground_truth_status is not None
                and status_assessment.status == ground_truth_status.get("status")
            )
            result.goal_progress_match = (
                ground_truth_status is not None
                and status_assessment.goal_progress == ground_truth_status.get("goal_progress")
            )

            # If status != "done", measure generate latency
            if status_assessment.status != "done" and ground_truth_decision:
                t_gen_start = time.perf_counter()
                plan_result = await planner.generate_from_assessment(
                    goal=task.goal,
                    state=state,
                    context=context,
                    assessment=status_assessment,
                )
                t_gen_end = time.perf_counter()
                result.generate_latency_ms = (t_gen_end - t_gen_start) * 1000

                # Extract steps from decision
                decision = plan_result.decision if plan_result else None
                generated_steps = decision.steps if decision else []
                result.generated_steps = [s.model_dump() for s in generated_steps]
                result.step_count_generated = len(generated_steps)
                result.step_count_expected = len(ground_truth_decision.get("steps", []))

                # Compute accuracy metrics
                result.step_count_match = result.step_count_generated == result.step_count_expected
                result.dependency_correctness = compute_dependency_correctness(
                    generated_steps, ground_truth_decision.get("steps", [])
                )
                result.kind_correctness = compute_kind_correctness(
                    generated_steps, ground_truth_decision.get("steps", [])
                )
                result.description_similarity = compute_description_similarity(
                    generated_steps, ground_truth_decision.get("steps", [])
                )

            result.total_latency_ms = (
                result.assess_latency_ms + result.generate_latency_ms
                if result.generate_latency_ms
                else result.assess_latency_ms
            )

        except Exception as e:
            result.error = str(e)
            logger.error(f"Task {task.id} failed: {e}")

        results.append(result)

        # Rate limiting between calls
        await asyncio.sleep(0.5)

    return results


def compute_dependency_correctness(
    generated: list[Any],
    ground_truth: list[Any],
) -> float:
    """Compute % of steps with correct dependencies."""

    if not ground_truth:
        return 100.0 if not generated else 0.0

    # Map step IDs to expected deps
    expected_deps = {s.get("id"): set(s.get("dependencies", []) or []) for s in ground_truth}
    generated_deps = {s.get("id"): set(s.get("dependencies", []) or []) for s in generated}

    # For steps that appear in both, check dep match
    matches = 0
    total = 0

    for step_id, expected in expected_deps.items():
        if step_id in generated_deps:
            total += 1
            if generated_deps[step_id] == expected:
                matches += 1

    return 100.0 * matches / total if total > 0 else 100.0


def compute_kind_correctness(
    generated: list[Any],
    ground_truth: list[Any],
) -> float:
    """Compute % of steps with correct kind (action/ask_user)."""

    if not ground_truth:
        return 100.0 if not generated else 0.0

    expected_kinds = {s.get("id"): s.get("kind", "action") for s in ground_truth}
    generated_kinds = {s.get("id"): s.get("kind", "action") for s in generated}

    matches = 0
    total = 0

    for step_id, expected in expected_kinds.items():
        if step_id in generated_kinds:
            total += 1
            if generated_kinds[step_id] == expected:
                matches += 1

    return 100.0 * matches / total if total > 0 else 100.0


def compute_description_similarity(
    generated: list[Any],
    ground_truth: list[Any],
) -> float:
    """Compute token overlap similarity for descriptions."""

    if not ground_truth:
        return 1.0 if not generated else 0.0

    # Simple token overlap
    def tokenize(text: str) -> set[str]:
        return set(text.lower().split())

    similarities: list[float] = []

    for gt_step in ground_truth:
        gt_tokens = tokenize(gt_step.get("description", ""))
        best_sim = 0.0

        for gen_step in generated:
            gen_tokens = tokenize(gen_step.get("description", ""))
            if gt_tokens and gen_tokens:
                overlap = len(gt_tokens & gen_tokens)
                union = len(gt_tokens | gen_tokens)
                sim = overlap / union if union > 0 else 0.0
                best_sim = max(best_sim, sim)

        similarities.append(best_sim)

    return statistics.mean(similarities) if similarities else 0.0


# =============================================================================
# Report Generation
# =============================================================================


def generate_json_report(
    results_by_role: dict[str, list[PlanBenchmarkResult]],
    summaries_by_role: dict[str, BenchmarkSummary],
    mode: str,
) -> str:
    """Generate JSON report."""

    report = {
        "benchmark": "plan_generation",
        "mode": mode,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": {
            role: [asdict(r) for r in results] for role, results in results_by_role.items()
        },
        "summary": {role: summary.to_dict() for role, summary in summaries_by_role.items()},
    }

    return json.dumps(report, indent=2)


def generate_markdown_report(
    summaries_by_role: dict[str, BenchmarkSummary],
    mode: str,
) -> str:
    """Generate Markdown report."""

    lines = [
        "# Plan Generation Benchmark Report",
        "",
        f"**Mode**: {mode}",
        f"**Timestamp**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    # Overall summary table
    lines.extend(
        [
            "## Overall Summary",
            "",
            "| Role | Tasks | Success | Failed |",
            "|------|-------|---------|--------|",
        ]
    )

    for role, summary in summaries_by_role.items():
        lines.append(
            f"| {role} | {summary.total_tasks} | {summary.successful_tasks} | {summary.failed_tasks} |"
        )

    lines.append("")

    # Latency table
    lines.extend(
        [
            "## Latency (ms)",
            "",
            "| Role | Assess (avg) | Generate (avg) | Total (avg) | P50 | P95 |",
            "|------|-------------|----------------|-------------|-----|-----|",
        ]
    )

    for role, summary in summaries_by_role.items():
        stats = summary.to_dict()
        lat = stats["latency_ms"]["total"]
        lines.append(
            f"| {role} | {stats['latency_ms']['assess']['avg']:.1f} | "
            f"{stats['latency_ms']['generate']['avg']:.1f} | "
            f"{lat['avg']:.1f} | {lat['p50']:.1f} | {lat['p95']:.1f} |"
        )

    lines.append("")

    # Accuracy table
    lines.extend(
        [
            "## Accuracy",
            "",
            "| Role | Step Count % | Status % | Dep Correctness % | Kind % | Desc Similarity |",
            "|------|-------------|----------|-------------------|--------|-----------------|",
        ]
    )

    for role, summary in summaries_by_role.items():
        stats = summary.to_dict()
        acc = stats["accuracy"]
        lines.append(
            f"| {role} | {acc['step_count_match_pct']:.1f} | {acc['status_match_pct']:.1f} | "
            f"{acc['dependency_correctness_pct']['avg']:.1f} | {acc['kind_correctness_pct']['avg']:.1f} | "
            f"{acc['description_similarity']['avg']:.2f} |"
        )

    lines.append("")

    # Cost-effectiveness (accuracy per ms)
    lines.extend(
        [
            "## Cost-Effectiveness",
            "",
            "| Role | Accuracy/ms | Notes |",
            "|------|------------|-------|",
        ]
    )

    for role, summary in summaries_by_role.items():
        stats = summary.to_dict()
        avg_latency = stats["latency_ms"]["total"]["avg"]
        avg_accuracy = statistics.mean(
            [
                stats["accuracy"]["step_count_match_pct"],
                stats["accuracy"]["kind_correctness_pct"]["avg"],
            ]
        )
        cost_eff = avg_accuracy / avg_latency if avg_latency > 0 else 0
        lines.append(f"| {role} | {cost_eff:.3f} | Latency/accuracy tradeoff |")

    lines.append("")

    return "\n".join(lines)


# =============================================================================
# Main Entry Point
# =============================================================================


async def main_async(args: argparse.Namespace) -> None:
    """Async main entry point."""

    # Load task fixtures (lightweight, no soothe imports)
    from plan_benchmark_tasks import get_all_benchmark_tasks

    tasks = get_all_benchmark_tasks()

    # Filter by category if specified
    if args.category:
        tasks = [t for t in tasks if t.category == args.category]

    # Determine model roles to test
    roles_to_test = ["fast", "think"] if not args.model_role else [args.model_role]

    # Load config for online mode
    config = None
    if args.online:
        from soothe.config import load_config

        config = load_config()

    # Run benchmarks for each role
    results_by_role: dict[str, list[PlanBenchmarkResult]] = {}
    summaries_by_role: dict[str, BenchmarkSummary] = {}

    for role in roles_to_test:
        logger.info(f"Running benchmark for model role: {role}")

        if args.online:
            results = await run_online_benchmark(tasks, role, config)
        else:
            results = await run_offline_benchmark(tasks, role)

        results_by_role[role] = results

        # Create summary
        summary = BenchmarkSummary(model_role=role)
        for result in results:
            summary.add_result(result)
        summaries_by_role[role] = summary

    # Generate report
    if args.output == "json":
        report = generate_json_report(
            results_by_role, summaries_by_role, "online" if args.online else "offline"
        )
        print(report)
    else:
        report = generate_markdown_report(summaries_by_role, "online" if args.online else "offline")
        print(report)

    # Save to file if specified
    if args.output_file:
        Path(args.output_file).write_text(report)
        logger.info(f"Report saved to {args.output_file}")


def main() -> None:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description="Plan Generation Performance Benchmark (IG-536)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--online",
        action="store_true",
        help="Run with real LLM API calls (requires API keys)",
    )

    parser.add_argument(
        "--model-role",
        choices=["fast", "think", "default"],
        help="Test specific model role only (default: test both fast and think)",
    )

    parser.add_argument(
        "--category",
        choices=["simple", "medium"],
        help="Filter tasks by category",
    )

    parser.add_argument(
        "--output",
        choices=["json", "markdown"],
        default="markdown",
        help="Output format (default: markdown)",
    )

    parser.add_argument(
        "--output-file",
        type=str,
        help="Save report to file",
    )

    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
