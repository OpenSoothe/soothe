#!/usr/bin/env python3
"""Cleanup orphaned checkpoint records before FK constraint enforcement.

Removes records from checkpoint_anchors and failed_branches tables
that reference non-existent loop_ids in agentloop_loops table.

Usage:
    python scripts/cleanup_orphaned_checkpoints.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def cleanup_orphaned_records(db_path: Path, dry_run: bool = True) -> dict:
    """Remove orphaned checkpoint records.

    Args:
        db_path: Path to loop_checkpoints.db
        dry_run: If True, report but don't delete

    Returns:
        Statistics of removed records
    """
    stats = {
        "orphaned_anchors": 0,
        "orphaned_branches": 0,
        "orphaned_goals": 0,
    }

    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row

        # Find valid loop_ids
        valid_loops = set(
            row[0] for row in db.execute("SELECT loop_id FROM agentloop_loops")
        )

        if not valid_loops:
            print("No valid loops found in database")
            return stats

        # Find orphaned anchors
        orphaned_anchors = db.execute(
            "SELECT anchor_id, loop_id, iteration FROM checkpoint_anchors "
            "WHERE loop_id NOT IN ({})".format(",".join("?" * len(valid_loops))),
            tuple(valid_loops),
        ).fetchall()

        stats["orphaned_anchors"] = len(orphaned_anchors)

        # Find orphaned branches
        orphaned_branches = db.execute(
            "SELECT branch_id, loop_id, iteration FROM failed_branches "
            "WHERE loop_id NOT IN ({})".format(",".join("?" * len(valid_loops))),
            tuple(valid_loops),
        ).fetchall()

        stats["orphaned_branches"] = len(orphaned_branches)

        # Find orphaned goals
        orphaned_goals = db.execute(
            "SELECT goal_id, loop_id FROM goal_records "
            "WHERE loop_id NOT IN ({})".format(",".join("?" * len(valid_loops))),
            tuple(valid_loops),
        ).fetchall()

        stats["orphaned_goals"] = len(orphaned_goals)

        if not dry_run:
            # Delete orphaned records
            if orphaned_anchors:
                db.execute(
                    "DELETE FROM checkpoint_anchors "
                    "WHERE loop_id NOT IN ({})".format(",".join("?" * len(valid_loops))),
                    tuple(valid_loops),
                )

            if orphaned_branches:
                db.execute(
                    "DELETE FROM failed_branches "
                    "WHERE loop_id NOT IN ({})".format(",".join("?" * len(valid_loops))),
                    tuple(valid_loops),
                )

            if orphaned_goals:
                db.execute(
                    "DELETE FROM goal_records "
                    "WHERE loop_id NOT IN ({})".format(",".join("?" * len(valid_loops))),
                    tuple(valid_loops),
                )

            db.commit()

            print(f"✓ Removed {stats['orphaned_anchors']} orphaned anchors")
            print(f"✓ Removed {stats['orphaned_branches']} orphaned branches")
            print(f"✓ Removed {stats['orphaned_goals']} orphaned goals")
        else:
            print(f"[DRY RUN] Would remove {stats['orphaned_anchors']} orphaned anchors")
            print(f"[DRY RUN] Would remove {stats['orphaned_branches']} orphaned branches")
            print(f"[DRY RUN] Would remove {stats['orphaned_goals']} orphaned goals")

            # Print sample orphaned loop_ids
            if orphaned_anchors:
                print("\nOrphaned loop_ids in anchors:")
                for row in orphaned_anchors[:5]:
                    print(f"  - {row['loop_id']} (iteration {row['iteration']})")

            if orphaned_branches:
                print("\nOrphaned loop_ids in branches:")
                for row in orphaned_branches[:5]:
                    print(f"  - {row['loop_id']} (iteration {row['iteration']})")

            if orphaned_goals:
                print("\nOrphaned loop_ids in goals:")
                for row in orphaned_goals[:5]:
                    print(f"  - {row['loop_id']}")

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Cleanup orphaned checkpoint records"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report but don't delete",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        help="Path to loop_checkpoints.db",
    )

    args = parser.parse_args()

    if args.db_path:
        db_path = Path(args.db_path)
    else:
        # Use default path from directory_manager
        from soothe_sdk.client.config import SOOTHE_DATA_DIR

        db_path = Path(SOOTHE_DATA_DIR) / "loop_checkpoints.db"

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        exit(1)

    print(f"Cleaning orphaned records from: {db_path}")
    stats = cleanup_orphaned_records(db_path, dry_run=args.dry_run)

    if args.dry_run:
        print("\nRun without --dry-run to actually remove records")