"""Unit tests for plan generation benchmark utilities (IG-536)."""

from __future__ import annotations

import statistics

# Import fixtures - pytest config sets pythonpath = ["tests"]
from fixtures.plan_benchmark_tasks import (
    CONTINUATION_TASKS,
    MEDIUM_TASKS,
    SIMPLE_TASKS,
    get_all_benchmark_tasks,
    get_task_by_id,
    get_tasks_by_category,
)


def test_fixture_counts() -> None:
    """Verify fixture counts match expected."""
    all_tasks = get_all_benchmark_tasks()
    assert len(all_tasks) == 12, f"Expected 12 tasks, got {len(all_tasks)}"
    assert len(SIMPLE_TASKS) == 5, f"Expected 5 simple tasks, got {len(SIMPLE_TASKS)}"
    assert len(MEDIUM_TASKS) == 5, f"Expected 5 medium tasks, got {len(MEDIUM_TASKS)}"
    assert len(CONTINUATION_TASKS) == 2, (
        f"Expected 2 continuation tasks, got {len(CONTINUATION_TASKS)}"
    )


def test_task_categories() -> None:
    """Verify task categories are correct."""
    simple = get_tasks_by_category("simple")
    assert len(simple) == 6  # 5 simple + 1 continuation simple (the other continuation is medium)
    assert all(t.category == "simple" for t in simple)

    medium = get_tasks_by_category("medium")
    assert len(medium) == 6  # 5 medium + 1 continuation medium
    assert all(t.category == "medium" for t in medium)


def test_task_lookup() -> None:
    """Verify task lookup by ID works."""
    task = get_task_by_id("simple-read-file")
    assert task is not None
    assert task.category == "simple"
    assert task.goal == "Read the README.md file and summarize its contents"

    task = get_task_by_id("nonexistent")
    assert task is None


def test_task_ground_truth_structure() -> None:
    """Verify ground truth has expected structure."""
    task = get_task_by_id("simple-read-file")
    assert task is not None

    # Check status ground truth
    assert task.ground_truth_status is not None
    assert "status" in task.ground_truth_status
    assert "goal_progress" in task.ground_truth_status
    assert "assessment_reasoning" in task.ground_truth_status

    # Check decision ground truth
    assert task.ground_truth_decision is not None
    assert "type" in task.ground_truth_decision
    assert "steps" in task.ground_truth_decision
    assert "execution_mode" in task.ground_truth_decision

    # Check steps structure
    steps = task.ground_truth_decision["steps"]
    assert len(steps) == 2
    assert all("id" in s for s in steps)
    assert all("description" in s for s in steps)
    assert all("kind" in s for s in steps)


def test_dependency_ground_truth() -> None:
    """Verify dependency steps have correct structure."""
    task = get_task_by_id("simple-read-file")
    assert task is not None

    steps = task.ground_truth_decision["steps"]
    dep_step = steps[1]  # "Summarize README contents"
    assert dep_step.get("dependencies") == ["01"]


def test_medium_task_complexity() -> None:
    """Verify medium tasks have 2-3 steps with dependencies."""
    for task in MEDIUM_TASKS:
        steps = task.ground_truth_decision["steps"]
        assert 2 <= len(steps) <= 3, f"Medium task {task.id} should have 2-3 steps"

        # At least one step should have dependencies
        has_deps = any(s.get("dependencies") for s in steps)
        assert has_deps, f"Medium task {task.id} should have dependent steps"

        # Execution mode should be "dependency"
        assert task.ground_truth_decision["execution_mode"] == "dependency"


def test_continuation_task_prior_progress() -> None:
    """Verify continuation tasks have prior progress."""
    for task in CONTINUATION_TASKS:
        assert task.iteration > 0, f"Continuation task {task.id} should have iteration > 0"
        assert task.prior_progress is not None, (
            f"Continuation task {task.id} should have prior_progress"
        )


def test_done_status_task() -> None:
    """Verify done status task has no decision."""
    task = get_task_by_id("medium-read-config-update-done")
    assert task is not None
    assert task.ground_truth_status["status"] == "done"
    assert task.ground_truth_decision is None, "Done status should have no decision"


def test_accuracy_scoring_logic() -> None:
    """Test accuracy scoring computation logic."""

    # Mock generated and ground truth steps for testing
    generated = [
        {"id": "01", "description": "Read file", "kind": "action", "dependencies": None},
        {"id": "02", "description": "Summarize", "kind": "action", "dependencies": ["01"]},
    ]

    ground_truth = [
        {"id": "01", "description": "Read README.md file", "kind": "action", "dependencies": None},
        {
            "id": "02",
            "description": "Summarize README contents",
            "kind": "action",
            "dependencies": ["01"],
        },
    ]

    # Test dependency correctness
    def compute_dependency_correctness(gen: list, gt: list) -> float:
        if not gt:
            return 100.0 if not gen else 0.0
        expected_deps = {s.get("id"): set(s.get("dependencies", []) or []) for s in gt}
        generated_deps = {s.get("id"): set(s.get("dependencies", []) or []) for s in gen}
        matches = 0
        total = 0
        for step_id, expected in expected_deps.items():
            if step_id in generated_deps:
                total += 1
                if generated_deps[step_id] == expected:
                    matches += 1
        return 100.0 * matches / total if total > 0 else 100.0

    score = compute_dependency_correctness(generated, ground_truth)
    assert score == 100.0, f"Expected 100% dependency correctness, got {score}"

    # Test kind correctness
    def compute_kind_correctness(gen: list, gt: list) -> float:
        if not gt:
            return 100.0 if not gen else 0.0
        expected_kinds = {s.get("id"): s.get("kind", "action") for s in gt}
        generated_kinds = {s.get("id"): s.get("kind", "action") for s in gen}
        matches = 0
        total = 0
        for step_id, expected in expected_kinds.items():
            if step_id in generated_kinds:
                total += 1
                if generated_kinds[step_id] == expected:
                    matches += 1
        return 100.0 * matches / total if total > 0 else 100.0

    score = compute_kind_correctness(generated, ground_truth)
    assert score == 100.0, f"Expected 100% kind correctness, got {score}"

    # Test description similarity (token overlap)
    def compute_description_similarity(gen: list, gt: list) -> float:
        if not gt:
            return 1.0 if not gen else 0.0

        def tokenize(text: str) -> set[str]:
            return set(text.lower().split())

        similarities: list[float] = []
        for gt_step in gt:
            gt_tokens = tokenize(gt_step.get("description", ""))
            best_sim = 0.0
            for gen_step in gen:
                gen_tokens = tokenize(gen_step.get("description", ""))
                if gt_tokens and gen_tokens:
                    overlap = len(gt_tokens & gen_tokens)
                    union = len(gt_tokens | gen_tokens)
                    sim = overlap / union if union > 0 else 0.0
                    best_sim = max(best_sim, sim)
            similarities.append(best_sim)
        return statistics.mean(similarities) if similarities else 0.0

    # "Read file" vs "Read README.md file" should have overlap
    # "file" is in both, "Read" is in both
    # For gt "Read README.md file": tokens = {read, readme.md, file}
    # For gen "Read file": tokens = {read, file}
    # Overlap = {read, file} = 2, Union = {read, readme.md, file} = 3
    # Similarity = 2/3 ≈ 0.67
    # For gt "Summarize README contents": tokens = {summarize, readme, contents}
    # For gen "Summarize": tokens = {summarize}
    # Overlap = {summarize} = 1, Union = {summarize, readme, contents} = 3
    # Similarity = 1/3 ≈ 0.33
    # Average = (0.67 + 0.33) / 2 ≈ 0.5
    score = compute_description_similarity(generated, ground_truth)
    assert 0.3 < score < 0.8, f"Expected moderate similarity (0.3-0.8), got {score}"
