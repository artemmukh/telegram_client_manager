# Project Context — Session Handoff

Snapshot written 2026-07-07 to migrate this in-progress work into a future session.
This is a scratch handoff doc, not permanent project documentation — safe to delete
once the work below is verified and committed.

## What this session was doing

Feature: **admin's clinic must propagate to created clients and appointments**, so
that clinic identity is visible during client search/delete/update and appointment
confirmation/cards. Previously `clinic_id` was `NULL` on admin-created clients even
though `UserRepository`'s `USER_SELECT` already LEFT JOINs `clinics` (so display was
already wired — creation just never populated the FK).

Design decisions made with the user (via AskUserQuestion):
1. **Clinic source of truth**: resolve the admin's clinic via the `staff` table
   (`StaffRepository.get_staff(telegram_id).clinic_id`), matching the pattern already
   used by `AppointmentManagement`. Not from `current_user`/middleware.
2. **Scope**: both the client-creation flow AND the appointment flow got the
   clinic-name treatment (not client-only).

## Concurrent user-driven refactor (already in progress when this session started)

The user was independently renaming/restructuring in parallel:
- `bot/handlers/admin/record_management/` → `bot/handlers/admin/appointment_management/`
  (git shows this as staged renames: `__init__.py`, `appointment_creation.py`,
  `appointment_delete.py`, `appointment_search.py`, `appointment_update.py`,
  `record_menu.py`).
- Note: only the **handlers** dir was renamed. Keyboards/states/services still live
  under `bot/keyboards/admin/record_management_kb/` and
  `bot/states/admin/record_management/` — this is intentional/current, don't "fix" it
  without asking.
- The user had also started editing `bot/services/client/client_management.py`
  directly and left a stray syntax error (`x            role=role,` on line 34) —
  this was fixed as part of this session's edit (see below).

Always re-`git status` / re-`Read` before editing anything in this area — the user
edits files concurrently with agent turns in this project.

## Files changed this session (uncommitted, NOT yet verified by tests)

New file:
- `bot/services/utils/clinic.py` — new shared helper
  `resolve_staff_clinic(staff_repository, clinic_repository, telegram_user_id) -> Clinic`.
  Raises `RoleError` if telegram_user_id isn't staff, `BotException` if the staff's
  clinic_id doesn't resolve to a `Clinic` row. Used by both `ClientManagement` and
  `AppointmentManagement` to avoid duplicating the staff→clinic lookup.

Modified:
- `bot/models/appointment.py` — added `clinic_name: str | None = None` field.
- `bot/repositories/appointment_repository.py` — `APPOINTMENT_SELECT` now aliases
  `appointments` as `a` and LEFT JOINs `clinics c ON c.id = a.clinic_id`, selecting
  `c.name AS clinic_name`. All three read queries (`get_appointment_by_id`,
  `get_appointments_by_client_id`, `get_appointments_by_telegram_id`) updated to use
  `a.`-qualified columns and the join. `_row_to_appointment` now reads `row[9]` into
  `clinic_name`.
- `bot/services/client/client_management.py` — `ClientManagement.__init__` now takes
  `(user_repository, staff_repository, clinic_repository)`. `create_client` signature
  changed to `create_client(admin_telegram_id: int, data: dict)`; it resolves the
  clinic via `get_admin_clinic()` (new method, wraps `resolve_staff_clinic`) and
  stamps `clinic_id`/`clinic_name` onto the new `User`. Fixed the pre-existing stray
  `x` syntax error on the `role=role` line while doing this edit.
- `bot/services/appointment/appointment_management.py` — `__init__` now also takes
  `clinic_repository`. `create_appointment` no longer calls `staff_repository`
  directly; it calls the new `get_admin_clinic()` method (same pattern as
  ClientManagement) and stamps `clinic_name` on the created `Appointment`. Removed
  now-unused `RoleError` import (moved into `resolve_staff_clinic`).
- `bot/handlers/utils/admin_utils/appointment_helpers.py` — `build_appointment_confirmation`
  now renders a `Клиника: {data.get('clinic_name', '')}` line; `build_appointment_card`
  conditionally renders `Клиника: {appointment.clinic_name}` if present.
- `bot/handlers/admin/client_management/client_creation.py` — router factory is now
  `create_admin_client_creation_router(user_repo, staff_repo, clinic_repo)`. The
  `create_client` entry handler resolves the admin's clinic up front (via
  `cl_mng.get_admin_clinic`) and stashes `clinic_id`/`clinic_name` into FSM state.
  `client_creation_finish` now passes `callback_query.from_user.id` into
  `create_client(...)` and shows `clinic_name` in the success message.
- `bot/handlers/admin/appointment_management/appointment_creation.py` — factory is now
  `create_admin_appointment_creation_router(appointment_repo, user_repo, staff_repo, clinic_repo)`.
  `create_record` entry resolves clinic via `appt_mng.get_admin_clinic` and stashes
  `clinic_name` into FSM state so `build_appointment_confirmation` can show it.
- `bot/handlers/admin/appointment_management/appointment_search.py`,
  `appointment_delete.py`, `appointment_update.py` — factories all gained a
  `clinic_repo` parameter, threaded into `AppointmentManagement(...)`.
- `bot/run.py` — updated all 5 call sites
  (`create_admin_client_creation_router`, `create_admin_appointment_creation_router`,
  `create_admin_appointment_search_router`, `create_admin_appointment_deletion_router`,
  `create_admin_appointment_update_router`) to pass `staff_repo`/`clinic_repo` as
  needed. `clinic_repo` was already constructed in `main()` from earlier work.
- `tests/test_client_management.py` — rewritten. Added local `FakeStaffRepo` /
  `FakeClinicRepo` and a `_service()` helper building
  `ClientManagement(user_repo, staff_repo, clinic_repo)`. All `create_client(...)`
  calls updated to the new `(admin_telegram_id, data)` signature. Added new test
  `test_client_management_rejects_non_staff` asserting `RoleError` when staff lookup
  fails. Existing tests now assert `clinic_id`/`clinic_name` on the created user.
- `tests/test_appointment_management.py` — added `FakeClinicRepo` + `_clinic_repo()`
  helper; every `AppointmentManagement(...)` construction updated to pass a 4th
  `clinic_repo` arg; `test_create_appointment_resolves_clinic_and_client` now also
  asserts `appointment.clinic_name == "Зуб Мудрости"`.

## NOT yet done / next steps for the next session

1. **Verification never completed this session** — the last action (py_compile of
   all changed files) was interrupted by the user switching model
   (`/model` → Sonnet 5) before results came back. **Do not assume the code compiles
   or tests pass.** Run before anything else:
   ```
   ./.venv/Scripts/python.exe -m py_compile bot/services/utils/clinic.py bot/models/appointment.py bot/repositories/appointment_repository.py bot/services/client/client_management.py bot/services/appointment/appointment_management.py bot/handlers/utils/admin_utils/appointment_helpers.py bot/handlers/admin/client_management/client_creation.py bot/handlers/admin/appointment_management/appointment_creation.py bot/handlers/admin/appointment_management/appointment_search.py bot/handlers/admin/appointment_management/appointment_delete.py bot/handlers/admin/appointment_management/appointment_update.py bot/run.py tests/test_client_management.py tests/test_appointment_management.py
   ```
   then run the full suite:
   ```
   ./.venv/Scripts/python.exe -m pytest -q --basetemp="$CLAUDE_JOB_DIR/tmp/pt"
   ```
   (pytest cache write to `.pytest_cache` throws a benign `PermissionError` on this
   machine — ignore it, or pass `--basetemp` as above.)
2. **Not checked**: whether any other caller of `ClientManagement(...)` or
   `AppointmentManagement(...)` exists outside the files touched above (e.g. other
   test files, or a `client_management_kb`/menu router that also instantiates the
   service). Grep for `ClientManagement(` and `AppointmentManagement(` before
   declaring this done.
3. **Not checked**: `client_creation.py`'s edit-flow branches
   (`client_creation_edit_full_name` / `client_creation_edit_phone`) still call
   `show_confirmation(message, state, ...)` which renders from `build_client_text`
   using `FIELDS` in `confirmations.py` — that dict includes `clinic_name`, so once
   `clinic_id`/`clinic_name` are in FSM state (stashed at `create_client` entry) they
   should show up automatically on edit/re-confirm screens too, but this was not
   manually traced end-to-end.
4. **Design note for the reviewer**: `resolve_staff_clinic` raising `RoleError` when
   an admin is not in the `staff` table is inherited behavior from
   `AppointmentManagement`'s original `create_appointment` — now shared. If an admin
   user is only in `users` (role=admin) but not in `staff`, client/appointment
   creation will now hard-fail with "Только сотрудник клиники может..." — confirm
   this matches intended access control (staff table currently seeded with 3
   hardcoded telegram IDs in `StaffRepository.init()`).
5. Once verified, this was going to be reviewed via the mandatory reviewer subagent
   per `CLAUDE.md` workflow, then committed. **Neither review nor commit happened.**
   All changes listed above are uncommitted in the working tree alongside the user's
   own concurrent rename-refactor (see git status at time of writing, captured in
   this file's companion session).

## Architecture reminders (from CLAUDE.md, for whoever picks this up)

- Handler → Service → Repository → Database, never bypass.
- No SQL outside repositories, no Telegram objects inside services.
- `resolve_staff_clinic` is a services/utils helper (not a repository) since it
  orchestrates two repositories — consistent with how `RegistrationService` and
  `AppointmentManagement` already compose repos in the service layer.
