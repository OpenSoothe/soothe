#!/usr/bin/env python3
"""
Event Naming Migration Script for RFC-403

Automates the migration of event type strings from old naming to unified semantics.
Generates migration report and supports dry-run mode.

Usage:
    python scripts/migrate_event_names.py --dry-run  # Preview changes
    python scripts/migrate_event_names.py           # Apply changes
    python scripts/migrate_event_names.py --report  # Generate report only
"""

import argparse
import re
from pathlib import Path


# Complete migration map from RFC-403 Section 8
EVENT_MIGRATION_MAP = {
    # Lifecycle events
    "soothe.lifecycle.thread.started": "soothe.lifecycle.thread.started",
    "soothe.lifecycle.thread.saving": "soothe.lifecycle.thread.saving",
    "soothe.lifecycle.checkpoint.saving": "soothe.lifecycle.checkpoint.saving",
    "soothe.system.daemon.heartbeat": "soothe.system.daemon.heartbeat",

    # Protocol events
    "soothe.protocol.memory.recalling": "soothe.protocol.memory.recalling",
    "soothe.protocol.memory.storing": "soothe.protocol.memory.storing",
    "soothe.protocol.policy.checking": "soothe.protocol.policy.checking",

    # Cognitive events
    "soothe.cognition.plan.creating": "soothe.cognition.plan.creating",
    "soothe.cognition.plan.step.started": "soothe.cognition.plan.step.started",
    "soothe.cognition.plan.reflecting": "soothe.cognition.plan.reflecting",
    "soothe.cognition.goal.creating": "soothe.cognition.goal.creating",
    "soothe.cognition.goal.directives_applying": "soothe.cognition.goal.directives_applying",
    "soothe.cognition.goal.deferring": "soothe.cognition.goal.deferring",
    "soothe.cognition.agent_loop.reasoning": "soothe.cognition.agent_loop.reasoning",

    # Capability events (subagents)
    "soothe.capability.browser.started": "soothe.capability.browser.started",
    "soothe.capability.browser.completed": "soothe.capability.browser.completed",
    "soothe.capability.browser.step.running": "soothe.capability.browser.step.running",
    "soothe.capability.browser.cdp.connecting": "soothe.capability.browser.cdp.connecting",
    "soothe.capability.claude.text.running": "soothe.capability.claude.text.running",
    "soothe.capability.claude.tool.running": "soothe.capability.claude.tool.running",
    "soothe.capability.claude.completed": "soothe.capability.claude.completed",
    "soothe.capability.research.started": "soothe.capability.research.started",
    "soothe.capability.research.completed": "soothe.capability.research.completed",
    "soothe.capability.research.analyzing": "soothe.capability.research.analyzing",
    "soothe.capability.research.questions.generating": "soothe.capability.research.questions.generating",
    "soothe.capability.research.queries.generating": "soothe.capability.research.queries.generating",
    "soothe.capability.research.gathering": "soothe.capability.research.gathering",
    "soothe.capability.research.gather.completed": "soothe.capability.research.gather.completed",
    "soothe.capability.research.summarizing": "soothe.capability.research.summarizing",
    "soothe.capability.research.reflecting": "soothe.capability.research.reflecting",
    "soothe.capability.research.reflection.completed": "soothe.capability.research.reflection.completed",
    "soothe.capability.research.synthesizing": "soothe.capability.research.synthesizing",
    "soothe.capability.research.internal_llm.running": "soothe.capability.research.internal_llm.running",
    "soothe.capability.research.judgement.reporting": "soothe.capability.research.judgement.reporting",

    # System events (autopilot)
    "soothe.system.autopilot.status_changed": "soothe.system.autopilot.status_changed",
    "soothe.system.autopilot.goal.creating": "soothe.system.autopilot.goal.creating",
    "soothe.system.autopilot.goal.reporting": "soothe.system.autopilot.goal.reporting",
    "soothe.system.autopilot.goal.completed": "soothe.system.autopilot.goal.completed",
    "soothe.system.autopilot.dreaming.started": "soothe.system.autopilot.dreaming.started",
    "soothe.system.autopilot.dreaming.completed": "soothe.system.autopilot.dreaming.completed",
    "soothe.system.autopilot.goal.validating": "soothe.system.autopilot.goal.validating",
    "soothe.system.autopilot.goal.suspending": "soothe.system.autopilot.goal.suspending",
    "soothe.system.autopilot.feedback.sending": "soothe.system.autopilot.feedback.sending",
    "soothe.system.autopilot.relationship.detecting": "soothe.system.autopilot.relationship.detecting",
    "soothe.system.autopilot.checkpoint.saving": "soothe.system.autopilot.checkpoint.saving",
    "soothe.system.autopilot.goal.blocking": "soothe.system.autopilot.goal.blocking",

    # Output events
    "soothe.output.chitchat.responding": "soothe.output.chitchat.responding",
    "soothe.output.autonomous.final_report.reporting": "soothe.output.autonomous.final_report.reporting",

    # Error events
    "soothe.error.general.failed": "soothe.error.general.failed",
}


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


def migrate_file(filepath: Path, dry_run: bool = True) -> dict[str, int]:
    """
    Migrate event type strings in a single file.

    Returns dict with migration stats:
        - 'replacements': number of replacements made
        - 'constants_updated': event constants updated
        - 'literals_updated': string literals updated
        - 'types_updated': type field defaults updated
    """
    try:
        content = filepath.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        # Skip files with encoding issues
        return stats
    original_content = content

    stats = {
        'replacements': 0,
        'constants_updated': 0,
        'literals_updated': 0,
        'types_updated': 0,
    }

    # Pattern 1: Event type string constants
    # Example: THREAD_CREATED = "soothe.lifecycle.thread.started"
    constant_pattern = re.compile(r'^([A-Z_]+)\s*=\s*"([^"]+)"$')

    # Pattern 2: Type field in event classes
    # Example: type: Literal["soothe.lifecycle.thread.started"] = "soothe.lifecycle.thread.started"
    type_pattern = re.compile(r'type:\s*Literal\["([^"]+)"\]\s*=\s*"([^"]+)"')

    # Pattern 3: Generic string literals
    # Example: "soothe.lifecycle.thread.started"
    literal_pattern = re.compile('"([^"]+)"')

    lines = content.split('\n')
    new_lines = []

    for line in lines:
        new_line = line

        # Check for event constant assignment
        constant_match = constant_pattern.match(line)
        if constant_match:
            const_name, old_type = constant_match.groups()
            if old_type in EVENT_MIGRATION_MAP:
                new_type = EVENT_MIGRATION_MAP[old_type]
                new_line = f'{const_name} = "{new_type}"'
                stats['constants_updated'] += 1
                stats['replacements'] += 1

        # Check for type field in event class
        type_match = type_pattern.search(line)
        if type_match:
            old_type1, old_type2 = type_match.groups()
            if old_type1 in EVENT_MIGRATION_MAP and old_type2 in EVENT_MIGRATION_MAP:
                new_type = EVENT_MIGRATION_MAP[old_type1]
                new_line = line.replace(old_type1, new_type).replace(old_type2, new_type)
                stats['types_updated'] += 1
                stats['replacements'] += 1

        # Check for generic string literals
        literals = literal_pattern.findall(line)
        for old_type in literals:
            if old_type in EVENT_MIGRATION_MAP:
                new_type = EVENT_MIGRATION_MAP[old_type]
                new_line = new_line.replace(f'"{old_type}"', f'"{new_type}"')
                stats['literals_updated'] += 1
                stats['replacements'] += 1

        new_lines.append(new_line)

    new_content = '\n'.join(new_lines)

    if not dry_run and new_content != original_content:
        filepath.write_text(new_content)

    return stats


def generate_migration_report(root_dir: Path) -> None:
    """Generate detailed migration report."""
    python_files = find_python_files(root_dir)

    report_lines = [
        "# Event Naming Migration Report",
        f"\n**Total files**: {len(python_files)}",
        f"**Total event migrations**: {len(EVENT_MIGRATION_MAP)}",
        "\n## Files Affected\n",
    ]

    total_replacements = 0
    affected_files = []

    for filepath in python_files:
        stats = migrate_file(filepath, dry_run=True)
        if stats['replacements'] > 0:
            affected_files.append((filepath, stats))
            total_replacements += stats['replacements']

    report_lines.append(f"**Files with changes**: {len(affected_files)}")
    report_lines.append(f"**Total replacements**: {total_replacements}\n")

    report_lines.append("\n## Detailed Changes\n")
    for filepath, stats in sorted(affected_files, key=lambda x: x[1]['replacements'], reverse=True):
        rel_path = filepath.relative_to(root_dir)
        report_lines.append(f"\n### {rel_path}")
        report_lines.append(f"- Constants: {stats['constants_updated']}")
        report_lines.append(f"- Type fields: {stats['types_updated']}")
        report_lines.append(f"- Literals: {stats['literals_updated']}")
        report_lines.append(f"- **Total**: {stats['replacements']}")

    report_content = '\n'.join(report_lines)
    report_path = root_dir / "docs" / "migration-report.md"
    report_path.write_text(report_content)

    print(f"Migration report generated: {report_path}")
    print(f"Files affected: {len(affected_files)}")
    print(f"Total replacements: {total_replacements}")


def main():
    parser = argparse.ArgumentParser(description="Migrate event names to RFC-403 semantics")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--report", action="store_true", help="Generate migration report only")
    parser.add_argument("--verbose", action="store_true", help="Show detailed output")

    args = parser.parse_args()

    root_dir = Path(__file__).parent.parent

    if args.report:
        generate_migration_report(root_dir)
        return

    python_files = find_python_files(root_dir)

    print(f"Found {len(python_files)} Python files")
    print(f"Migration map: {len(EVENT_MIGRATION_MAP)} event types")

    if args.dry_run:
        print("\n=== DRY RUN MODE (no changes will be written) ===\n")

    total_replacements = 0
    affected_files = 0

    for filepath in python_files:
        stats = migrate_file(filepath, dry_run=args.dry_run)

        if stats['replacements'] > 0:
            affected_files += 1
            total_replacements += stats['replacements']

            if args.verbose:
                rel_path = filepath.relative_to(root_dir)
                print(f"\n{rel_path}:")
                print(f"  Constants: {stats['constants_updated']}")
                print(f"  Type fields: {stats['types_updated']}")
                print(f"  Literals: {stats['literals_updated']}")

    print(f"\n{'=' * 60}")
    print(f"Summary:")
    print(f"  Files affected: {affected_files}")
    print(f"  Total replacements: {total_replacements}")

    if args.dry_run:
        print("\nRun without --dry-run to apply changes")
    else:
        print("\n✓ Migration complete")
        print("\nNext steps:")
        print("  1. Run 'make lint' to check for errors")
        print("  2. Run 'make test-unit' to verify tests")
        print("  3. Run './scripts/validate_event_names.py' to validate")


if __name__ == "__main__":
    main()