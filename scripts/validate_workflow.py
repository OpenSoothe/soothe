#!/usr/bin/env python3
"""
Workflow validation script for GitHub Actions YAML files.

Validates syntax and conditional logic for docker.yml and release-docker.yml.
"""

import sys
from pathlib import Path

import yaml


def check_condition_syntax(condition: str, context: str) -> list[str]:
    """Check GitHub Actions expression syntax."""
    errors = []

    if "secrets." in condition:
        errors.append(f"ERROR: Secrets cannot be used in if conditions ({context}): {condition}")

    # Check for common syntax issues
    if "${{" in condition and "}}" not in condition:
        errors.append(f"Unbalanced expression brackets in: {condition}")
    if "}}" in condition and "${{" not in condition:
        errors.append(f"Unbalanced expression brackets in: {condition}")

    # Check for proper comparison operators
    if "==" in condition or "!=" in condition:
        # Should be inside ${{ }}
        if "${{" not in condition or "}}" not in condition:
            errors.append(f"Comparison outside expression: {condition}")

    # Check for invalid operators
    invalid_ops = ["&&", "||"]
    for op in invalid_ops:
        if op in condition:
            # Should be inside ${{ }}
            if "${{" not in condition:
                errors.append(f"Operator '{op}' outside expression: {condition}")

    return errors


def validate_docker_yml(workflow: dict) -> list[str]:
    """Validate docker.yml specific logic."""
    errors = []

    # Check triggers - handle YAML parsing 'on' as boolean True
    # In YAML 1.1, 'on' is parsed as boolean True
    triggers = workflow.get("on") or workflow.get(True, {})

    # Handle case where 'on' might be a list or have complex structure
    trigger_names = set()
    if isinstance(triggers, dict):
        trigger_names = set(triggers.keys())
    elif isinstance(triggers, list):
        trigger_names = set(triggers)

    # Manual branch builds only (release builds use release-docker.yml).
    if "workflow_dispatch" not in trigger_names:
        errors.append("ERROR: Missing workflow_dispatch trigger")

    # Check job conditions (look for any job, not just 'build')
    jobs = workflow.get("jobs", {})
    build_job = (
        jobs.get("build-and-push") or jobs.get("build") or list(jobs.values())[0] if jobs else {}
    )
    if "if" in build_job:
        cond = build_job["if"]
        if "workflow_run" in str(cond):
            errors.append(f"WARNING: Job condition references workflow_run: {cond}")

    # Check for required outputs
    steps = build_job.get("steps", [])
    outputs_found = {}
    for step in steps:
        step_id = step.get("id", "")
        if step_id:
            outputs_found[step_id] = step.get("outputs", {})

    # Validate metadata tags
    for step in steps:
        step_name = step.get("name", "")
        if "metadata" in step_name.lower() or "tags" in step_name.lower():
            # Check tags configuration
            with_ = step.get("with", {})
            tags = with_.get("tags", "")
            if tags:
                if "publish_version_tags" in tags:
                    print("  ✓ Version tags conditional: present")
                if "publish_branch_tags" in tags:
                    print("  ✓ Branch tags conditional: present")

    return errors


def validate_release_docker_yml(workflow: dict) -> list[str]:
    """Validate release-docker.yml specific logic."""
    errors = []

    # Check triggers - handle YAML parsing 'on' as boolean True
    # In YAML 1.1, 'on' is parsed as boolean True
    triggers = workflow.get("on") or workflow.get(True, {})

    # Handle case where 'on' might have complex structure
    trigger_names = set()
    if isinstance(triggers, dict):
        trigger_names = set(triggers.keys())
    elif isinstance(triggers, list):
        trigger_names = set(triggers)

    if "workflow_run" not in trigger_names:
        errors.append("ERROR: Missing workflow_run trigger")
    elif isinstance(triggers, dict):
        wr = triggers.get("workflow_run", {})
        if wr.get("workflows") != ["Release Soothe Packages"]:
            errors.append(
                f"ERROR: workflow_run should trigger on 'Release Soothe Packages', got: {wr.get('workflows')}"
            )
        if wr.get("types") != ["completed"]:
            errors.append(
                f"ERROR: workflow_run should trigger on 'completed', got: {wr.get('types')}"
            )
        branches = wr.get("branches") or []
        if branches in (["main"], ["master"], ["main", "master"], ["master", "main"]):
            errors.append(
                "ERROR: workflow_run branches [main, master] never match release tag runs "
                "(Release Soothe Packages head_branch is e.g. v0.7.14). Use a 'v*' pattern."
            )

    # Check for required steps (look for any job, not just 'build')
    jobs = workflow.get("jobs", {})
    build_job = (
        jobs.get("build-and-push") or jobs.get("build") or list(jobs.values())[0] if jobs else {}
    )
    steps = build_job.get("steps", [])
    step_names = [s.get("name", "") for s in steps]

    required_steps = [
        ("Wait for PyPI", ["wait", "pypi"]),
        ("Check PyPI availability", ["pypi"]),
        ("Extract version", ["extract", "version"]),
        ("Set up QEMU", ["qemu"]),
        ("Set up Docker Buildx", ["buildx"]),
    ]

    for req_name, keywords in required_steps:
        if not any(all(kw in name.lower() for kw in keywords) for name in step_names):
            errors.append(f"WARNING: Missing expected step: {req_name}")
        else:
            print(f"  ✓ Found step: {req_name}")

    # Check for exponential backoff logic
    for step in steps:
        step_name = step.get("name", "")
        if "check" in step_name.lower() and "pypi" in step_name.lower():
            # Look for retry pattern
            if "retry" in str(step).lower() or "loop" in str(step).lower():
                print(f"  ✓ Found retry logic in: {step_name}")

    return errors


def main():
    """Run validation on workflow files."""
    print("=" * 60)
    print("Workflow Syntax and Logic Validation")
    print("=" * 60)

    all_errors = []

    # Validate docker.yml
    print("\n📄 Validating docker.yml...")
    docker_path = Path(".github/workflows/docker.yml")
    if docker_path.exists():
        with open(docker_path) as f:
            workflow = yaml.safe_load(f)
        errors = validate_docker_yml(workflow)
        if errors:
            all_errors.extend([(docker_path, e) for e in errors])
            for e in errors:
                print(f"  ✗ {e}")
        else:
            print("  ✓ All checks passed")
    else:
        print(f"  ✗ File not found: {docker_path}")
        all_errors.append((docker_path, "File not found"))

    # Validate release-docker.yml
    print("\n📄 Validating release-docker.yml...")
    release_path = Path(".github/workflows/release-docker.yml")
    if release_path.exists():
        with open(release_path) as f:
            workflow = yaml.safe_load(f)
        errors = validate_release_docker_yml(workflow)
        if errors:
            all_errors.extend([(release_path, e) for e in errors])
            for e in errors:
                print(f"  ✗ {e}")
        else:
            print("  ✓ All checks passed")
    else:
        print(f"  ✗ File not found: {release_path}")
        all_errors.append((release_path, "File not found"))

    # Check conditional expressions
    print("\n📄 Checking conditional expressions...")
    for wf_path in [docker_path, release_path]:
        if wf_path.exists():
            with open(wf_path) as f:
                content = yaml.safe_load(f)

            jobs = content.get("jobs", {})
            for job_name, job in jobs.items():
                if "if" in job:
                    cond_errors = check_condition_syntax(job["if"], f"{job_name} job")
                    all_errors.extend([(wf_path, e) for e in cond_errors])

                for step_idx, step in enumerate(job.get("steps", [])):
                    if "if" in step:
                        step_name = step.get("name", f"step {step_idx}")
                        cond_errors = check_condition_syntax(step["if"], f"{job_name}/{step_name}")
                        all_errors.extend([(wf_path, e) for e in cond_errors])

                    with_ = step.get("with", {})
                    for field in ("push",):
                        value = with_.get(field)
                        if isinstance(value, str) and "secrets." in value:
                            step_name = step.get("name", f"step {step_idx}")
                            all_errors.append(
                                (
                                    wf_path,
                                    f"ERROR: Secrets cannot be used in step inputs ({job_name}/{step_name}.{field}): {value}",
                                )
                            )

    if not any(e[1].startswith("ERROR") for e in all_errors):
        print("  ✓ All conditional expressions valid")

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    errors_only = [e for e in all_errors if "ERROR" in e[1]]
    warnings = [e for e in all_errors if "WARNING" in e[1]]

    if errors_only:
        print(f"\n❌ Found {len(errors_only)} error(s):")
        for path, err in errors_only:
            print(f"  - {path.name}: {err}")
        return 1

    if warnings:
        print(f"\n⚠️  Found {len(warnings)} warning(s):")
        for path, err in warnings:
            print(f"  - {path.name}: {err}")

    print("\n✅ Workflow validation passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
