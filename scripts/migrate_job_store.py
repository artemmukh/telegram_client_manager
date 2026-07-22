#!/usr/bin/env python3
"""
Migrate job store: shift expire_pending_request_job run times 2 hours earlier.

Run this BEFORE deploying the new version to production.
It updates all existing expire_pending_request_job entries in the SQLite job store
to run 2 hours before their current scheduled time (to match the new logic).

Usage:
    python scripts/migrate_job_store.py
"""

import sqlite3
import pickle
from datetime import datetime, timedelta
from pathlib import Path

def migrate_job_store():
    """Update expire_pending_request_job timings in the job store."""

    jobstore_path = Path("data/reminders.db")

    if not jobstore_path.exists():
        print("[OK] No job store found (data/reminders.db). Nothing to migrate.")
        return

    conn = sqlite3.connect(jobstore_path)
    cursor = conn.cursor()

    try:
        # Strategy 1: Try deserializing job objects to find expire_pending_request_job entries
        cursor.execute("SELECT id, next_run_time, job_state FROM apscheduler_jobs")
        rows = cursor.fetchall()

        expire_pending_jobs = []

        for job_id, next_run_time, job_state in rows:
            # Try to deserialize and check func_ref
            try:
                job_obj = pickle.loads(job_state)
                func_ref = job_obj.func_ref if hasattr(job_obj, 'func_ref') else None
                if func_ref and 'expire_pending_request_job' in str(func_ref):
                    expire_pending_jobs.append((job_id, next_run_time))
            except Exception:
                pass

        # Strategy 2: Fallback - check job IDs matching the pattern (appt_*_expire)
        if not expire_pending_jobs:
            cursor.execute("SELECT id, next_run_time FROM apscheduler_jobs WHERE id LIKE '%_expire'")
            expire_pending_jobs = cursor.fetchall()

        if not expire_pending_jobs:
            print("[OK] No expire_pending_request_job entries found. Nothing to migrate.")
            conn.close()
            return

        print("[INFO] Found {} expire_pending_request_job entries to migrate:".format(
            len(expire_pending_jobs)))

        # Update each job: shift run_date 2 hours earlier
        migrated_count = 0
        for job_id, old_run_time in expire_pending_jobs:
            try:
                # next_run_time is stored as Unix timestamp (float)
                old_datetime = datetime.fromtimestamp(old_run_time)
                new_datetime = old_datetime - timedelta(hours=2)
                new_run_time = new_datetime.timestamp()

                print("  {}: {} -> {}".format(job_id, old_datetime.isoformat(), new_datetime.isoformat()))

                cursor.execute(
                    "UPDATE apscheduler_jobs SET next_run_time = ? WHERE id = ?",
                    (new_run_time, job_id)
                )
                migrated_count += 1

            except Exception as e:
                print("  [WARN] {}: Could not update ({})".format(job_id, e))

        conn.commit()
        print("\n[OK] Migrated {} job(s)".format(migrated_count))

    except sqlite3.OperationalError as e:
        print("[ERROR] Database error: {}".format(e))

    finally:
        conn.close()


if __name__ == "__main__":
    print("Migrating job store: expire_pending_request_job timing (2h earlier)...\n")
    migrate_job_store()
    print("\nDone! Safe to start the bot.")
