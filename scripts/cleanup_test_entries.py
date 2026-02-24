#!/usr/bin/env python3
"""Clean up test entries from staging queue.

This script removes test entries identified by keywords in their content.
"""

import sqlite3
import sys
from pathlib import Path


def cleanup_test_entries(db_path: Path, dry_run: bool = True) -> None:
    """Clean up test entries from staging queue.

    Args:
        db_path: Path to SQLite database.
        dry_run: If True, only show what would be deleted.
    """
    # Test keywords to identify test entries
    test_keywords = [
        "Testing ecosystem",
        "Testing complete flow",
        "Verify full flow",
        "End-to-end test",
        "E2E",
        "test entry",
        "dummy",
        "sample",
    ]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Find entries matching test keywords
    test_entries = []
    cursor.execute("SELECT id, content FROM staging_queue WHERE status = 'pending'")

    for row in cursor.fetchall():
        entry_id, content_json = row
        # Check if any test keyword appears in the content
        if any(keyword.lower() in content_json.lower() for keyword in test_keywords):
            test_entries.append(entry_id)

    if not test_entries:
        print("✅ No test entries found to clean up")
        conn.close()
        return

    print(f"Found {len(test_entries)} test entries:")
    for entry_id in test_entries:
        cursor.execute(
            "SELECT id, json_extract(content, '$.problem') FROM staging_queue WHERE id = ?",
            (entry_id,),
        )
        result = cursor.fetchone()
        if result:
            print(f"  - {result[0]}: {result[1][:80]}...")

    if dry_run:
        print("\n🔍 DRY RUN - No entries deleted")
        print("Run with --execute to actually delete these entries")
    else:
        # Delete test entries
        placeholders = ",".join("?" * len(test_entries))
        cursor.execute(
            f"DELETE FROM staging_queue WHERE id IN ({placeholders})",
            test_entries,
        )
        conn.commit()
        print(f"\n✅ Deleted {len(test_entries)} test entries")

    conn.close()


if __name__ == "__main__":
    db_path = Path.home() / ".claude" / "knowledge-bridge" / "knowledge_bridge.db"

    if not db_path.exists():
        print(f"❌ Database not found at {db_path}")
        sys.exit(1)

    dry_run = "--execute" not in sys.argv

    cleanup_test_entries(db_path, dry_run=dry_run)
