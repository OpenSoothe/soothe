#!/usr/bin/env python3
"""Cleanup script to fix orphaned running goals in loop_checkpoints.db.

This script repairs data corruption caused by the index calculation bug
where goals were added to goal_history AFTER current_goal_index was computed.

Bug: checkpoint.current_goal_index = len(goal_history) - 1  # BEFORE append
     checkpoint.goal_history.append(goal_record)             # AFTER index

Result: goals with index=-1 but status='running' (orphaned)

This script:
1. Finds loops with current_goal_index=-1 but goals with status='running'
2. Repairs by setting current_goal_index to the last running goal
3. Updates loop status to 'running' if there are active goals
"""

import sqlite3
import sys
from pathlib import Path


def find_orphaned_goals(db_path: Path) -> list[dict]:
    """Find loops with orphaned running goals.

    Args:
        db_path: Path to loop_checkpoints.db

    Returns:
        List of orphaned goal records with loop metadata
    """
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA foreign_keys=ON")

        cursor = db.execute("""
            SELECT
                l.loop_id,
                l.current_goal_index,
                l.status,
                l.thread_ids,
                g.goal_id,
                g.goal_text,
                g.status as goal_status,
                g.iteration,
                g.started_at
            FROM agentloop_loops l
            JOIN goal_records g ON l.loop_id = g.loop_id
            WHERE l.current_goal_index = -1
            AND g.status = 'running'
            ORDER BY g.started_at DESC
        """)

        orphaned = []
        for row in cursor.fetchall():
            orphaned.append({
                "loop_id": row[0],
                "current_goal_index": row[1],
                "loop_status": row[2],
                "thread_ids": row[3],
                "goal_id": row[4],
                "goal_text": row[5],
                "goal_status": row[6],
                "iteration": row[7],
                "started_at": row[8],
            })

        return orphaned


def repair_orphaned_goals(db_path: Path, dry_run: bool = True) -> int:
    """Repair orphaned running goals by setting correct goal_index.

    Args:
        db_path: Path to loop_checkpoints.db
        dry_run: If True, only report what would be fixed

    Returns:
        Number of loops repaired
    """
    orphaned = find_orphaned_goals(db_path)

    if not orphaned:
        print("✅ No orphaned goals found. Database is healthy.")
        return 0

    print(f"⚠️  Found {len(orphaned)} orphaned running goals:")
    print()

    # Group by loop_id
    loops_with_orphans = {}
    for record in orphaned:
        loop_id = record["loop_id"]
        if loop_id not in loops_with_orphans:
            loops_with_orphans[loop_id] = []
        loops_with_orphans[loop_id].append(record)

    for loop_id, goals in loops_with_orphans.items():
        print(f"Loop: {loop_id}")
        print(f"  Current index: -1 (BUG)")
        print(f"  Loop status: {goals[0]['loop_status']}")
        print(f"  Orphaned goals:")
        for goal in goals:
            print(f"    - {goal['goal_id']}: '{goal['goal_text'][:50]}...'")
            print(f"      Status: {goal['goal_status']}, Iteration: {goal['iteration']}")
        print()

    if dry_run:
        print("🔍 DRY RUN - No changes made. To apply fixes, run with --apply")
        return len(loops_with_orphans)

    # Apply repairs
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA foreign_keys=ON")

        repaired_count = 0
        for loop_id, goals in loops_with_orphans.items():
            # Find the last running goal (most recent)
            last_goal = goals[-1]

            # Get total goal count for this loop
            cursor = db.execute(
                "SELECT COUNT(*) FROM goal_records WHERE loop_id = ?",
                (loop_id,)
            )
            goal_count = cursor.fetchone()[0]

            # Set current_goal_index to last goal (goal_count - 1)
            new_index = goal_count - 1

            # Update loop
            db.execute("""
                UPDATE agentloop_loops
                SET current_goal_index = ?,
                    status = 'running',
                    updated_at = datetime('now')
                WHERE loop_id = ?
            """, (new_index, loop_id))

            print(f"✅ Repaired loop {loop_id}:")
            print(f"  Set current_goal_index = {new_index}")
            print(f"  Set status = 'running'")
            print(f"  Active goal: {last_goal['goal_id']}")
            print()

            repaired_count += 1

        db.commit()

    print(f"🎉 Successfully repaired {repaired_count} loops with orphaned goals")
    return repaired_count


def verify_repair(db_path: Path) -> bool:
    """Verify that no orphaned goals remain after repair.

    Args:
        db_path: Path to loop_checkpoints.db

    Returns:
        True if database is healthy, False if orphaned goals remain
    """
    orphaned = find_orphaned_goals(db_path)

    if orphaned:
        print("❌ Verification failed: Still have orphaned goals!")
        for record in orphaned:
            print(f"  Loop {record['loop_id']}: Goal {record['goal_id']}")
        return False

    print("✅ Verification passed: No orphaned goals found")

    # Additional check: verify all running goals have valid index
    with sqlite3.connect(db_path) as db:
        cursor = db.execute("""
            SELECT l.loop_id, l.current_goal_index, g.goal_id
            FROM agentloop_loops l
            JOIN goal_records g ON l.loop_id = g.loop_id
            WHERE l.status = 'running'
            AND g.status = 'running'
            AND l.current_goal_index >= 0
        """)

        running_goals = cursor.fetchall()
        if running_goals:
            print(f"✅ Found {len(running_goals)} loops with properly indexed running goals")
            for row in running_goals[:3]:
                print(f"  Loop {row[0]}: index={row[1]}, goal={row[2]}")

    return True


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Fix orphaned running goals in loop_checkpoints.db")
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to loop_checkpoints.db (default: ~/.soothe/data/loop_checkpoints.db)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply repairs (default: dry run only)"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify repairs after applying"
    )

    args = parser.parse_args()

    # Resolve db_path
    if args.db_path:
        db_path = Path(args.db_path)
    else:
        from soothe_sdk.client.config import SOOTHE_DATA_DIR
        db_path = Path(SOOTHE_DATA_DIR) / "loop_checkpoints.db"

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        sys.exit(1)

    print(f"📂 Database: {db_path}")
    print()

    if args.verify:
        success = verify_repair(db_path)
        sys.exit(0 if success else 1)

    # Run repair (dry_run=False if --apply flag set)
    repaired = repair_orphaned_goals(db_path, dry_run=not args.apply)

    if args.apply and repaired > 0:
        print()
        print("🔍 Running verification...")
        success = verify_repair(db_path)
        sys.exit(0 if success else 1)

    sys.exit(0)


if __name__ == "__main__":
    main()