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

### 2. Deploy New Code

Pull and start the bot:

```bash
git pull
python -m bot.main  # or your startup command
```

### 3. What Changed

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

### 4. Verification

After deployment, verify:

```bash
# Check that bot starts without errors
tail -f logs/bot.log | grep -E "Auto-confirm|pending.*expiry"

# Should see:
# - Existing reminders loading: "Scheduled reminder for appointment..."
# - New auto-confirms loading: "Scheduled auto-confirm for appointment..."
```

### 5. Rollback (If Needed)

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
