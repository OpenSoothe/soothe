"""Plan generation benchmark task fixtures with ground truth (IG-536).

Provides simulated tasks for evaluating LLMPlanner latency and accuracy.
Each task includes a goal, mocked context, and expected plan (ground truth).

This module uses raw dicts instead of importing soothe types to avoid
circular import issues when running from scripts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BenchmarkTask:
    """A single benchmark task with ground truth plan.

    Attributes:
        id: Unique task identifier.
        category: Task complexity category ("simple" or "medium").
        goal: The user goal string to plan for.
        iteration: Current iteration number (0 for first wave).
        prior_progress: Optional prior progress description for iteration > 0.
        ground_truth_status: Expected status assessment (dict with status, goal_progress, assessment_reasoning).
        ground_truth_decision: Expected plan decision (dict with steps, execution_mode, reasoning).
    """

    id: str
    category: str  # "simple" | "medium"
    goal: str
    iteration: int = 0
    prior_progress: str | None = None
    ground_truth_status: dict | None = None
    ground_truth_decision: dict | None = None


# =============================================================================
# SIMPLE TASKS (1-2 steps, no dependencies)
# =============================================================================

SIMPLE_TASKS: list[BenchmarkTask] = [
    BenchmarkTask(
        id="simple-read-file",
        category="simple",
        goal="Read the README.md file and summarize its contents",
        iteration=0,
        ground_truth_status={
            "status": "continue",
            "goal_progress": "none",
            "assessment_reasoning": "I'm starting fresh — no prior evidence yet.",
            "require_goal_completion": False,
        },
        ground_truth_decision={
            "plan_action": "new",
            "type": "execute_steps",
            "steps": [
                {
                    "id": "01",
                    "description": "Read README.md file",
                    "expected_output": "README.md contents loaded",
                    "kind": "action",
                },
                {
                    "id": "02",
                    "description": "Summarize README contents",
                    "expected_output": "Brief summary of README sections",
                    "kind": "action",
                    "dependencies": ["01"],
                },
            ],
            "execution_mode": "dependency",
            "reasoning": "Read then summarize requires sequential execution.",
        },
    ),
    BenchmarkTask(
        id="simple-list-directory",
        category="simple",
        goal="List all Python files in the src/ directory",
        iteration=0,
        ground_truth_status={
            "status": "continue",
            "goal_progress": "none",
            "assessment_reasoning": "I'm starting fresh — need to enumerate Python files.",
            "require_goal_completion": False,
        },
        ground_truth_decision={
            "plan_action": "new",
            "type": "execute_steps",
            "steps": [
                {
                    "id": "01",
                    "description": "List Python files in src/",
                    "expected_output": "List of .py files in src/ directory",
                    "kind": "action",
                },
            ],
            "execution_mode": "parallel",
            "reasoning": "Single step to enumerate files.",
        },
    ),
    BenchmarkTask(
        id="simple-check-version",
        category="simple",
        goal="Check the current version in pyproject.toml",
        iteration=0,
        ground_truth_status={
            "status": "continue",
            "goal_progress": "none",
            "assessment_reasoning": "I'm starting fresh — need to read pyproject.toml.",
            "require_goal_completion": False,
        },
        ground_truth_decision={
            "plan_action": "new",
            "type": "execute_steps",
            "steps": [
                {
                    "id": "01",
                    "description": "Read version from pyproject.toml",
                    "expected_output": "Version string extracted from project config",
                    "kind": "action",
                },
            ],
            "execution_mode": "parallel",
            "reasoning": "Single read operation.",
        },
    ),
    BenchmarkTask(
        id="simple-git-status",
        category="simple",
        goal="Show the current git status",
        iteration=0,
        ground_truth_status={
            "status": "continue",
            "goal_progress": "none",
            "assessment_reasoning": "I'm starting fresh — need to run git status.",
            "require_goal_completion": False,
        },
        ground_truth_decision={
            "plan_action": "new",
            "type": "execute_steps",
            "steps": [
                {
                    "id": "01",
                    "description": "Run git status command",
                    "expected_output": "Current git status output",
                    "kind": "action",
                },
            ],
            "execution_mode": "parallel",
            "reasoning": "Single shell command.",
        },
    ),
    BenchmarkTask(
        id="simple-find-config",
        category="simple",
        goal="Find the main configuration file",
        iteration=0,
        ground_truth_status={
            "status": "continue",
            "goal_progress": "none",
            "assessment_reasoning": "I'm starting fresh — need to search for config files.",
            "require_goal_completion": False,
        },
        ground_truth_decision={
            "plan_action": "new",
            "type": "execute_steps",
            "steps": [
                {
                    "id": "01",
                    "description": "Search for config files",
                    "expected_output": "Location of main config file identified",
                    "kind": "action",
                },
            ],
            "execution_mode": "parallel",
            "reasoning": "Single search operation.",
        },
    ),
]


# =============================================================================
# MEDIUM TASKS (2-3 steps with dependencies)
# =============================================================================

MEDIUM_TASKS: list[BenchmarkTask] = [
    BenchmarkTask(
        id="medium-read-config-update",
        category="medium",
        goal="Read the current timeout setting from config.yml and update it to 60 seconds",
        iteration=0,
        ground_truth_status={
            "status": "continue",
            "goal_progress": "none",
            "assessment_reasoning": "I'm starting fresh — need to read then update config.",
            "require_goal_completion": False,
        },
        ground_truth_decision={
            "plan_action": "new",
            "type": "execute_steps",
            "steps": [
                {
                    "id": "01",
                    "description": "Read config.yml for timeout setting",
                    "full_description": "Read the config.yml file and locate the current timeout setting value. Use output from step 01; do NOT repeat step 01's actions.",
                    "expected_output": "Current timeout value identified",
                    "kind": "action",
                },
                {
                    "id": "02",
                    "description": "Update timeout to 60 seconds",
                    "full_description": "Edit config.yml to change the timeout setting to 60 seconds. Use output from step 01; do NOT repeat step 01's discovery actions.",
                    "expected_output": "config.yml updated with timeout=60",
                    "kind": "action",
                    "dependencies": ["01"],
                },
            ],
            "execution_mode": "dependency",
            "reasoning": "Read→write requires sequential execution; must find current value before editing.",
        },
    ),
    BenchmarkTask(
        id="medium-count-lines",
        category="medium",
        goal="Find all Python files in the packages/ directory and count total lines of code",
        iteration=0,
        ground_truth_status={
            "status": "continue",
            "goal_progress": "none",
            "assessment_reasoning": "I'm starting fresh — need to enumerate files then count lines.",
            "require_goal_completion": False,
        },
        ground_truth_decision={
            "plan_action": "new",
            "type": "execute_steps",
            "steps": [
                {
                    "id": "01",
                    "description": "List Python files in packages/",
                    "expected_output": "List of all .py files in packages/",
                    "kind": "action",
                },
                {
                    "id": "02",
                    "description": "Count total lines across all files",
                    "full_description": "Count lines of code across all Python files found in step 01. Use output from step 01; do NOT repeat enumeration.",
                    "expected_output": "Total line count calculated",
                    "kind": "action",
                    "dependencies": ["01"],
                },
            ],
            "execution_mode": "dependency",
            "reasoning": "Must enumerate files before counting lines.",
        },
    ),
    BenchmarkTask(
        id="medium-diagnose-fix",
        category="medium",
        goal="Find why the tests are failing in test_auth.py and fix the issue",
        iteration=0,
        ground_truth_status={
            "status": "continue",
            "goal_progress": "none",
            "assessment_reasoning": "I'm starting fresh — need to run tests then diagnose.",
            "require_goal_completion": False,
        },
        ground_truth_decision={
            "plan_action": "new",
            "type": "execute_steps",
            "steps": [
                {
                    "id": "01",
                    "description": "Run failing tests to capture errors",
                    "expected_output": "Test failure output captured",
                    "kind": "action",
                },
                {
                    "id": "02",
                    "description": "Diagnose root cause from errors",
                    "full_description": "Analyze test failure output to identify root cause. Use output from step 01; do NOT re-run tests.",
                    "expected_output": "Root cause identified",
                    "kind": "action",
                    "dependencies": ["01"],
                },
                {
                    "id": "03",
                    "description": "Fix the identified issue",
                    "full_description": "Apply fix to test_auth.py based on diagnosis. Use output from step 02; do NOT repeat diagnosis.",
                    "expected_output": "Fix applied to source",
                    "kind": "action",
                    "dependencies": ["02"],
                },
            ],
            "execution_mode": "dependency",
            "reasoning": "Diagnose→fix chain requires sequential execution.",
        },
    ),
    BenchmarkTask(
        id="medium-check-format",
        category="medium",
        goal="Check if the code passes linting and fix any issues found",
        iteration=0,
        ground_truth_status={
            "status": "continue",
            "goal_progress": "none",
            "assessment_reasoning": "I'm starting fresh — need to run linter then fix.",
            "require_goal_completion": False,
        },
        ground_truth_decision={
            "plan_action": "new",
            "type": "execute_steps",
            "steps": [
                {
                    "id": "01",
                    "description": "Run linter to find issues",
                    "expected_output": "Lint errors identified",
                    "kind": "action",
                },
                {
                    "id": "02",
                    "description": "Fix linting issues",
                    "full_description": "Fix all linting errors found in step 01. Use output from step 01; do NOT re-run linter first.",
                    "expected_output": "All lint errors fixed",
                    "kind": "action",
                    "dependencies": ["01"],
                },
            ],
            "execution_mode": "dependency",
            "reasoning": "Check→fix pattern requires sequential execution.",
        },
    ),
    BenchmarkTask(
        id="medium-search-replace",
        category="medium",
        goal="Find all uses of deprecated function 'old_api' and replace with 'new_api'",
        iteration=0,
        ground_truth_status={
            "status": "continue",
            "goal_progress": "none",
            "assessment_reasoning": "I'm starting fresh — need to find occurrences then replace.",
            "require_goal_completion": False,
        },
        ground_truth_decision={
            "plan_action": "new",
            "type": "execute_steps",
            "steps": [
                {
                    "id": "01",
                    "description": "Search for old_api usage",
                    "expected_output": "All files with old_api references found",
                    "kind": "action",
                },
                {
                    "id": "02",
                    "description": "Replace old_api with new_api",
                    "full_description": "Replace all occurrences of old_api with new_api in files found in step 01. Use output from step 01; do NOT re-search.",
                    "expected_output": "All replacements applied",
                    "kind": "action",
                    "dependencies": ["01"],
                },
            ],
            "execution_mode": "dependency",
            "reasoning": "Search→replace requires finding occurrences first.",
        },
    ),
]


# =============================================================================
# ITERATION > 0 TASKS (with prior progress)
# =============================================================================

CONTINUATION_TASKS: list[BenchmarkTask] = [
    BenchmarkTask(
        id="simple-read-file-continue",
        category="simple",
        goal="Read the README.md file and summarize its contents",
        iteration=1,
        prior_progress="Step 01 executed: README.md contents loaded (450 lines, sections: Installation, Usage, Configuration, Contributing)",
        ground_truth_status={
            "status": "continue",
            "goal_progress": "medium",
            "assessment_reasoning": "I've loaded the README.md file (450 lines with 4 sections), so I need to summarize it now.",
            "require_goal_completion": False,
        },
        ground_truth_decision={
            "plan_action": "new",
            "type": "execute_steps",
            "steps": [
                {
                    "id": "02",
                    "description": "Summarize README contents",
                    "expected_output": "Brief summary of README sections",
                    "kind": "action",
                },
            ],
            "execution_mode": "parallel",
            "reasoning": "Read step completed; need to summarize the loaded content.",
        },
    ),
    BenchmarkTask(
        id="medium-read-config-update-done",
        category="medium",
        goal="Read the current timeout setting from config.yml and update it to 60 seconds",
        iteration=2,
        prior_progress="Step 01: config.yml read, timeout=30 found. Step 02: Updated timeout to 60, saved config.yml.",
        ground_truth_status={
            "status": "done",
            "goal_progress": "complete",
            "assessment_reasoning": "I've read the config.yml, found timeout=30, and updated it to 60 seconds — the goal is complete.",
            "require_goal_completion": True,
        },
        ground_truth_decision=None,  # No plan needed when status=done
    ),
]


def get_all_benchmark_tasks() -> list[BenchmarkTask]:
    """Return all benchmark tasks."""
    return SIMPLE_TASKS + MEDIUM_TASKS + CONTINUATION_TASKS


def get_tasks_by_category(category: str) -> list[BenchmarkTask]:
    """Filter tasks by category."""
    return [t for t in get_all_benchmark_tasks() if t.category == category]


def get_task_by_id(task_id: str) -> BenchmarkTask | None:
    """Get a specific task by ID."""
    for task in get_all_benchmark_tasks():
        if task.id == task_id:
            return task
    return None


def task_to_plan_context(task: BenchmarkTask) -> dict:
    """Convert a BenchmarkTask to a PlanContext-like dict for benchmarking.

    Returns a dict with context fields that can be used to build a mock PlanContext.
    """
    return {
        "goal": task.goal,
        "iteration": task.iteration,
        "prior_progress": task.prior_progress,
        "workspace": "/workspace/example",  # Mock workspace
        "available_capabilities": ["explore", "web_search"],
        "completed_steps": [],
    }
