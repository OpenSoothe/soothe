#!/usr/bin/env python3
"""
Event Naming Validation Script for RFC-403

Validates all event type strings against RFC-403 unified naming semantics.

Usage:
    python scripts/validate_event_names.py           # Validate all events
    python scripts/validate_event_names.py --strict  # Fail on any violation
"""

import argparse
import re
import sys
from pathlib import Path


# Approved vocabularies from RFC-403 Section 4.4
APPROVED_DOMAINS = [
    "lifecycle", "protocol", "cognition", "capability",
    "output", "system", "error", "plugin"
]

APPROVED_VERBS = [
    "started", "resumed", "saving", "ended", "running",
    "checking", "recalling", "creating", "reflecting", "storing",
    "dispatching", "completed", "failed", "displaying", "emitting",
    "analyzing", "synthesizing", "reasoning", "deferring", "applying",
    "validating", "suspending", "blocking", "detecting", "sending",
    "responding", "reporting", "generating", "gathering", "summarizing",
    "connecting"
]

APPROVED_STATE_NOUNS = [
    "report", "heartbeat", "snapshot", "status_changed",
    "loaded", "unloaded", "health_checked"
]


def extract_event_types(filepath: Path) -> list[str]:
    """Extract all event type strings from a Python file."""
    try:
        content = filepath.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        # Skip files with encoding issues
        return []
    event_types = []

    # Pattern 1: Event type string constants
    # Example: THREAD_CREATED = "soothe.lifecycle.thread.started"
    constant_pattern = re.compile(r'^[A-Z_]+\s*=\s*"([^"]+)"$')

    # Pattern 2: Type field in event classes
    # Example: type: Literal["soothe.lifecycle.thread.started"] = "soothe.lifecycle.thread.started"
    type_pattern = re.compile(r'type:\s*Literal\["([^"]+)"\]')

    # Pattern 3: Generic string literals matching soothe.*
    literal_pattern = re.compile('"soothe\\.[^"]+"')

    for line in content.split('\n'):
        # Extract from constants
        match = constant_pattern.match(line)
        if match:
            event_type = match.group(1)
            if event_type.startswith("soothe."):
                event_types.append(event_type)

        # Extract from type fields
        match = type_pattern.search(line)
        if match:
            event_type = match.group(1)
            event_types.append(event_type)

        # Extract from generic literals
        matches = literal_pattern.findall(line)
        event_types.extend(matches)

    return event_types


def validate_event_type(event_type: str) -> list[str]:
    """
    Validate a single event type string against RFC-403 rules.

    Returns list of violations (empty if valid).
    """
    violations = []

    # Rule 1: Must match soothe.<domain>.<component>.<action> format
    parts = event_type.split('.')
    if len(parts) < 4:
        violations.append(f"Invalid format: {event_type} (expected 4+ segments)")
        return violations

    if parts[0] != "soothe":
        violations.append(f"Missing 'soothe' prefix: {event_type}")
        return violations

    domain = parts[1]

    # Rule 2: Domain must be approved OR plugin.<vendor>
    if domain == "plugin":
        # Core plugin events (loaded, failed, etc.) or plugin.<vendor>
        if len(parts) == 3:  # e.g., soothe.plugin.loaded
            action = parts[2]
            if action not in APPROVED_STATE_NOUNS and action != "failed":
                violations.append(f"Plugin lifecycle event must be state noun: {action}")
        elif len(parts) >= 4:  # e.g., soothe.plugin.acme.collector.started
            # Third-party plugin event, validate vendor namespace
            vendor = parts[2] if len(parts) >= 3 else None
            parts[3] if len(parts) >= 4 else None
            action = parts[4] if len(parts) >= 5 else parts[-1]

            # Vendor should not be a core domain
            if vendor in APPROVED_DOMAINS:
                violations.append(f"Plugin vendor '{vendor}' conflicts with core domain")

            # Action must still be approved
            if action not in APPROVED_VERBS and action not in APPROVED_STATE_NOUNS:
                violations.append(f"Action '{action}' not in approved vocabulary")
    else:
        # Standard event, validate domain
        if domain not in APPROVED_DOMAINS:
            violations.append(f"Domain '{domain}' not approved (must be one of: {APPROVED_DOMAINS})")

        # Validate action
        parts[2] if len(parts) >= 3 else ""
        action = parts[-1]  # Last segment

        # Allow hierarchical components (e.g., agent_loop.step)
        # Action must be approved
        if action not in APPROVED_VERBS and action not in APPROVED_STATE_NOUNS:
            violations.append(f"Action '{action}' not in approved vocabulary (verbs: {APPROVED_VERBS}, nouns: {APPROVED_STATE_NOUNS})")

    return violations


def find_python_files(root_dir: Path) -> list[Path]:
    """Find all Python files in the project."""
    exclude_dirs = {".git", "__pycache__", ".pytest_cache", "venv", "node_modules"}
    python_files = []

    for path in root_dir.rglob("*.py"):
        # Skip excluded directories
        if any(excluded in path.parts for excluded in exclude_dirs):
            continue
        python_files.append(path)

    return python_files


def main():
    parser = argparse.ArgumentParser(description="Validate event names against RFC-403")
    parser.add_argument("--strict", action="store_true", help="Exit with error on any violation")
    parser.add_argument("--verbose", action="store_true", help="Show all events and validation results")

    args = parser.parse_args()

    root_dir = Path(__file__).parent.parent
    python_files = find_python_files(root_dir)

    print(f"Validating event names in {len(python_files)} files...")
    print(f"Approved domains: {APPROVED_DOMAINS}")
    print(f"Approved verbs: {len(APPROVED_VERBS)}")
    print(f"Approved state nouns: {len(APPROVED_STATE_NOUNS)}")

    all_violations = []
    total_events = 0
    valid_events = 0

    for filepath in python_files:
        event_types = extract_event_types(filepath)

        for event_type in event_types:
            total_events += 1
            violations = validate_event_type(event_type)

            if violations:
                all_violations.append((filepath, event_type, violations))
            else:
                valid_events += 1

                if args.verbose:
                    print(f"✓ {event_type}")

    # Report results
    print(f"\n{'=' * 60}")
    print("Validation Summary:")
    print(f"  Total events checked: {total_events}")
    print(f"  Valid events: {valid_events}")
    print(f"  Violations found: {len(all_violations)}")

    if all_violations:
        print(f"\n{'=' * 60}")
        print("Violations:")
        for filepath, event_type, violations in all_violations:
            rel_path = filepath.relative_to(root_dir)
            print(f"\n{rel_path}:")
            print(f"  Event: {event_type}")
            for violation in violations:
                print(f"  ✗ {violation}")

    # Exit status
    if args.strict and all_violations:
        print(f"\n✗ Validation FAILED: {len(all_violations)} violations")
        sys.exit(1)
    elif all_violations:
        print(f"\n⚠ Validation warnings: {len(all_violations)} violations (run with --strict to fail)")
        sys.exit(0)
    else:
        print("\n✓ Validation PASSED: All events conform to RFC-403")
        sys.exit(0)


if __name__ == "__main__":
    main()