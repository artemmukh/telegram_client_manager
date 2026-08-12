# Staff Notification Details Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every non-deletion appointment activity log shown to staff compact by default, with localized `Подробнее` / `Скрыть` controls that toggle the authorized appointment card.

**Architecture:** Extract the existing completion-details pattern into a single staff-log details callback and keyboard pair. Persist the exact localized compact text with each staff activity notification after Telegram returns its message ID; this preserves historical facts such as a previous proposed time after the appointment has changed again. The callback carries only `appointment_id`; the handler identifies the notification row from the callback message's chat/message IDs, checks current clinic/doctor scope, reloads the full card for `Подробнее`, and restores the persisted compact text for `Скрыть`.

**Tech Stack:** Python, aiogram 3, aiosqlite, pytest, pytest-asyncio.

## Global Constraints

- Scope is staff-facing appointment activity logs: actions of the current staff member, colleagues, and clients as delivered to admins/doctors. Client-facing notifications are out of scope.
- Every non-deletion result notification is compact by default and has `Подробнее`; the expanded full appointment card has only `Скрыть`.
- Existing actionable request keyboards remain unchanged until an action is resolved: new booking requests, reschedule requests, completion follow-ups, and client negotiation controls.
- A lost race edits the stale action message immediately to the same compact result that a passive recipient sees; it must not leave the old action buttons or a full card without `Скрыть`.
- Delete notifications remain terminal: retain their current alert/text and remove actions; do not provide details because the appointment row no longer exists.
- Callback data contains only the appointment ID; no patient name, phone, date, service, actor label, event text, or notification ID is exposed in Telegram callback data.
- Details must be denied when the appointment no longer exists or is outside the viewer's current clinic/doctor scope.
- Preserve the distinction between `AppointmentAlreadyDecidedError` and `AppointmentAlreadyFinalizedError`.
- Do not stage, commit, or push without explicit user authorization.

---

### Task 1: Persist compact staff-log text and add the shared callback contract

**Files:**
- Create: `bot/keyboards/admin/record_management_kb/appointment_log_details_cb.py`
- Create: `bot/keyboards/admin/record_management_kb/appointment_log_details_kb.py`
- Modify: `bot/models/appointment_notification.py`
- Modify: `bot/repositories/appointment_repository.py`
- Modify: `bot/services/appointment/appointment_management.py`
- Modify: `bot/handlers/utils/admin_utils/appointment_decision_helpers.py`
- Modify: `bot/handlers/admin/appointment_management/appointment_completion.py`
- Test: `tests/test_appointment_completion.py`
- Test: `tests/test_appointment_repository.py`
- Test: repository fakes in affected service/handler test modules

**Interfaces:**
- `AppointmentLogDetailsCB(appointment_id: int)` and `AppointmentLogHideDetailsCB(appointment_id: int)` use distinct typed prefixes.
- `appointment_log_details_kb(appointment_id, lang)` and `appointment_log_hide_details_kb(appointment_id, lang)` return one localized button.
- `AppointmentNotification` gains nullable `compact_text`; legacy/action-only rows keep it `None`.
- `AppointmentRepository` adds a scoped lookup by `appointment_id`, `chat_id`, and `message_id`, plus a method to set `compact_text` for an existing action prompt.
- `staff_appointment_log_text(...)` renders a compact message once at delivery time; the stored result is the source of truth after `Скрыть`.
- `get_appointment_for_admin()` remains the authorization boundary for both callbacks.

- [ ] Write failing repository tests for the nullable `compact_text` migration, save/update operations, and chat/message-scoped lookup; update every fake repository used by the new service contract.
- [ ] Run `python -m pytest -q tests/test_appointment_repository.py` and confirm the new cases fail before the schema and methods exist.
- [ ] Add portable `compact_text TEXT NULL` schema upgrade in `AppointmentRepository.init()`, map it in the domain model, and preserve all existing `kind` lookup behavior.
- [ ] Write failing handler tests for `Подробнее → Скрыть` on a completion result, including a missing compact-log row and an out-of-scope appointment.
- [ ] Replace completion-only details callbacks/keyboards with the generic contract; look up compact text from the callback message and preserve the exact delivered actor/outcome wording after hiding details.
- [ ] Run `python -m pytest -q tests/test_appointment_repository.py tests/test_appointment_completion.py` and `python -m ruff check` for the modified modules.

### Task 2: Convert resolved booking, reschedule, cancellation, and creation staff logs

**Files:**
- Modify: `bot/services/appointment/appointment_notifications.py`
- Modify: `bot/handlers/utils/admin_utils/appointment_decision_helpers.py`
- Modify: `bot/handlers/admin/appointment_management/booking_requests.py`
- Modify: `bot/handlers/admin/appointment_management/reschedule_requests.py`
- Modify: `bot/handlers/admin/appointment_management/appointment_creation.py`
- Modify: `bot/handlers/admin/appointment_management/appointment_browser.py`
- Test: `tests/test_appointment_notifications.py`
- Test: `tests/test_staff_decision_notifications.py`

**Interfaces:**
- Result notification methods accept or derive the persisted `Appointment`, compact event kind, and deciding actor ID needed by the shared details renderer.
- `notify_staff_appointment_created`, staff booking decision notifications, staff reschedule decision notifications, client-proposal accepted/rejected logs, client cancellation/changed-time logs, and staff cancellation logs send the compact text with `appointment_log_details_kb`, then persist that exact text against the sent chat/message ID.
- Notification senders for unresolved booking/reschedule requests retain their existing action keyboards.

- [ ] Add failing service tests that every non-deletion staff result sender attaches the shared details keyboard and persists the exact recipient-localized compact text.
- [ ] Add failing flow tests for admin/doctor creation, client booking confirmation/rejection, client reschedule decision, client proposed-time response, client cancellation, and staff cancellation fan-out.
- [ ] Update the senders and fan-out helpers to render compact event-specific text plus the shared keyboard, resolving the recipient language as they do today.
- [ ] Keep deleted-appointment notification behavior unchanged and explicitly assert that it has no details keyboard.
- [ ] Run `python -m pytest -q tests/test_appointment_notifications.py tests/test_staff_decision_notifications.py tests/test_appointment_booking_handler.py tests/test_appointment_reschedule_handler.py`.

### Task 3: Convert own-success and stale-race message edits

**Files:**
- Modify: `bot/handlers/admin/appointment_management/appointment_completion.py`
- Modify: `bot/handlers/admin/appointment_management/booking_requests.py`
- Modify: `bot/handlers/admin/appointment_management/reschedule_requests.py`
- Modify: `bot/handlers/admin/appointment_management/appointment_browser.py`
- Modify: `bot/handlers/utils/admin_utils/appointment_decision_helpers.py`
- Test: `tests/test_appointment_completion.py`
- Test: `tests/test_appointment_decision_conflicts.py`
- Test: `tests/test_appointment_finalized_handlers.py`

**Interfaces:**
- A successful staff action records or updates compact text for its initiating notification, edits the message to the full card with `Скрыть`, and hiding returns the corresponding stored compact success log with `Подробнее`.
- An `AppointmentAlreadyDecidedError` updates both the stale message and its stored compact text directly to the compact colleague/client outcome with `Подробнее`.
- An `AppointmentAlreadyFinalizedError` retains the existing finalization-specific alert and keyboard removal.

- [ ] Write failing tests for successful own completion, booking decision, reschedule decision, and cancellation: full card first, then compact card after `Скрыть`.
- [ ] Write failing race tests for each actionable notification: the second actor's message is compact immediately, names the actual deciding actor, and opens details.
- [ ] Implement the shared edit helper and replace full-card/no-keyboard stale-race edits without moving business rules into handlers.
- [ ] Run `python -m pytest -q tests/test_appointment_completion.py tests/test_appointment_decision_conflicts.py tests/test_appointment_finalized_handlers.py tests/test_reschedule_requests_propose_handler.py`.

### Task 4: Regression verification and manual QA

**Files:**
- Modify: `docs/manual_qa_checklist.md`
- Test: all focused notification and appointment-management suites above

- [ ] Add manual checks for each activity source: colleague action, own action, client booking decision, client time change, client cancellation, and completion race.
- [ ] Add explicit checks that unresolved action prompts still expose their operational buttons and deletion notifications do not expose details.
- [ ] Run `python -m pytest -q` and `python -m ruff check` for every modified Python file, then `git diff --check`.
- [ ] Have a reviewer confirm no callback bypasses scope checks, no action keyboard survives a resolved race, and no client-facing notification was changed.
