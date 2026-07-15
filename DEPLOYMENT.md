# Deployment Guide

## Pre-Deployment Checklist for Auto-Confirm & Pending Expiry Changes

When deploying the auto-confirm client notification + pending expiry timing fix, follow these steps:

### 1. Run Job Store Migration (CRITICAL)

Before starting the bot with the new code, run the migration script to update existing jobs:

```bash
python scripts/migrate_job_store.py
```

This updates all existing `expire_pending_request_job` entries in the SQLite job store (`data/reminders.db`) to:
- Run **2 hours before** the appointment (instead of at appointment time)
- Match the new logic

**Why this matters:**
- Old jobs were scheduled for `appointment.datetime`
- New code expects jobs at `appointment.datetime - 2h`
- Without migration, admin approval window would be broken for existing pending requests

### 2. Run Users Created-At Timezone Migration (CRITICAL, one-time)

Before starting the bot with the new code, run this script once to correct
historical client registration timestamps:

```bash
python scripts/migrate_users_created_at_timezone.py
```

This shifts every existing `users.created_at` value in the main bot
database (`data/data_base.db`) **+5 hours**, converting them from UTC
(SQLite's `CURRENT_TIMESTAMP` default, which the old code silently relied
on) to Asia/Tashkent time (UTC+5), matching how `appointments.created_at`
has always been written.

**Why this matters:**
- `appointments.created_at` has always been written explicitly in
  Tashkent time by the application code.
- `users.created_at` was never passed explicitly on insert, so it silently
  fell back to SQLite's `CURRENT_TIMESTAMP` default, which is UTC.
- This created a systematic 5-hour gap between a client's registration
  date and their appointment dates. New code now writes
  `users.created_at` explicitly in Tashkent time, same as appointments;
  this script one-time-corrects the existing historical rows to match.

**WARNING: Do not run this script more than once against the same
database.** It unconditionally shifts every non-NULL `users.created_at`
by +5 hours with no idempotency guard — running it twice will double-shift
the data.

This script touches **only** the `users.created_at` column in the main
bot database. It does **not** touch `appointments.created_at` /
`status_updated_at` (already correct), and it does **not** touch
`data/reminders.db` (the separate APScheduler job store used by
reminders, auto-confirm, and pending/reschedule expiry jobs) — that file
is untouched by this migration.

### 3. Deploy New Code

Pull and start the bot:

```bash
git pull
python -m bot.main  # or your startup command
```

### 4. What Changed

#### New Features
- ✅ Auto-confirm notification to client when admin-created PENDING appointment is auto-confirmed 2h before appointment
- ✅ Pending client self-booking requests now expire **2 hours before** appointment (was: at appointment time)

#### Job Schedule
- **auto_confirm_pending_job** (ADMIN-created PENDING)
  - Fires: 2 hours before appointment
  - Action: PENDING → CONFIRMED + notify client

- **expire_pending_request_job** (CLIENT-created PENDING) 
  - Fires: 2 hours before appointment (CHANGED from appointment time)
  - Action: PENDING → EXPIRED + notify client

#### Approval Window
For CLIENT self-booking requests:
- Admin has **2 hours** before appointment to approve/reject
- After 2 hours, request auto-expires

### 5. Verification

After deployment, verify:

```bash
# Check that bot starts without errors
tail -f logs/bot.log | grep -E "Auto-confirm|pending.*expiry"

# Should see:
# - Existing reminders loading: "Scheduled reminder for appointment..."
# - New auto-confirms loading: "Scheduled auto-confirm for appointment..."
```

### 6. Rollback (If Needed)

If issues occur:

```bash
# Restore previous code
git reset --hard HEAD~5

# Clear corrupted job store (will lose active reminders, but safe)
rm data/reminders.db

# Restart bot
```

---

## Technical Details

### Job Store Schema

Jobs are persisted in SQLite (`data/reminders.db`) with structure:
- `id`: Job identifier (e.g., `appt_123_expire`, `appt_456_autoconf`)
- `next_run_time`: Unix timestamp (FLOAT)
- `job_state`: Pickled job object

The migration script:
1. Loads each job's pickled state
2. Identifies `expire_pending_request_job` entries
3. Shifts `next_run_time` 2 hours earlier
4. Saves back to database

### Race Condition Safety

- **auto_confirm** only fires for `created_by=ADMIN` + `status=PENDING`
- **expire_pending** only fires for `created_by=CLIENT` + `status=PENDING`
- Conditions are mutually exclusive → no race condition
- Status guard prevents double-execution if both attempt to update simultaneously

---

## Commits in This Change

- `caf6808`: Add auto-confirm notification + fix pending expiry timing
- `5bdb662`: Fix test expectations for 2h timing
- `a4660a6`: Fix docstring clarity
- `7322826`: Add migration script

---

**Questions?** Check `bot/services/appointment/appointment_jobs.py` and `bot/services/appointment/appointment_scheduler.py` for implementation details.
