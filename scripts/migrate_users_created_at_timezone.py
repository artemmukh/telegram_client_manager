#!/usr/bin/env python3
"""
Migrate users.created_at: shift existing rows +5 hours (UTC -> Asia/Tashkent).

Run this ONCE before deploying the new version to production.
Existing users.created_at values were written by SQLite's CURRENT_TIMESTAMP
default (always UTC). New code now writes Asia/Tashkent time explicitly
(UTC+5), matching how appointments.created_at already works. This script
one-time-corrects historical rows to match.

Usage:
    python scripts/migrate_users_created_at_timezone.py

WARNING: Do not run this script more than once against the same database --
it unconditionally shifts every non-NULL users.created_at by +5 hours with
no idempotency guard. Running it twice will double-shift the data.
"""

import sqlite3
from pathlib import Path


def migrate_users_created_at():
    """Shift users.created_at +5 hours for all existing rows."""

    db_path = Path("data/data_base.db")

    if not db_path.exists():
        print("[OK] No database found (data/data_base.db). Nothing to migrate.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT COUNT(*) FROM users WHERE created_at IS NOT NULL")
        count = cursor.fetchone()[0]

        if count == 0:
            print("[OK] No users with created_at set. Nothing to migrate.")
            return

        print(f"[INFO] Found {count} user(s) with created_at to migrate.")

        cursor.execute(
            "UPDATE users SET created_at = datetime(created_at, '+5 hours') "
            "WHERE created_at IS NOT NULL"
        )
        conn.commit()

        print(f"\n[OK] Migrated {count} user(s)")

    except sqlite3.OperationalError as e:
        print(f"[ERROR] Database error: {e}")

    finally:
        conn.close()


if __name__ == "__main__":
    print("Migrating users.created_at: UTC -> Asia/Tashkent (+5 hours)...\n")
    migrate_users_created_at()
    print("\nDone! Safe to start the bot.")
