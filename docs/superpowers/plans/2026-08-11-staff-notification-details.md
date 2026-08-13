# Staff Notification Details Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every non-deletion appointment activity log shown to staff compact by default, with localized `Подробнее` / `Скрыть` controls that toggle the authorized appointment card. Give client-facing result or terminal notifications without operational controls the same compact → `Подробнее` → client-safe full card → `Скрыть` → original compact-text cycle using the same shared callback payload and storage pattern; client action prompts remain unchanged.

**Architecture:** Extract the existing completion-details pattern into a single shared callback and keyboard pair. Persist the exact localized compact text with each staff activity notification after Telegram returns its message ID; this preserves historical facts such as a previous proposed time after the appointment has changed again. Client result notifications use the same persistence model: after Telegram returns their message ID, store their exact localized compact text in a `client_log` notification row. The shared callback payload carries only `appointment_id`; each handler locates the matching row by the callback message's chat/message IDs, authorizes the viewer, shows the appropriate full card for `Подробнее`, and restores the stored compact text for `Скрыть`. Staff uses `get_appointment_for_admin()` and the staff card; client uses `get_appointment_for_client()` and a client-safe card that never exposes staff-only data.

**Tech Stack:** Python, aiogram 3, aiosqlite, pytest, pytest-asyncio.

## Global Constraints

- Scope is staff-facing appointment activity logs: actions of the current staff member, colleagues, and clients as delivered to admins/doctors, plus client-facing result or terminal notifications that have no operational buttons. Each eligible client result follows compact → `Подробнее` → client-safe card → `Скрыть` → the exact original compact text.
- Every non-deletion result notification is compact by default and has `Подробнее`; the expanded full appointment card has only `Скрыть`.
- Existing actionable request keyboards remain unchanged until an action is resolved: new booking requests, reschedule requests, completion follow-ups, and client negotiation controls.
- Client-facing action or negotiation prompts retain their existing operational controls and must not be converted to compact/detail-only notifications.
- Client-facing non-control result/terminal notifications get both `Подробнее` and, while expanded, `Скрыть`. The restored view must be the exact localized compact text sent for that result, not a re-render of the appointment's later state.
- Client full cards may contain only data the client is already authorized to view for their own appointment. The allowed displayed fields are appointment ID as display text only, clinic name, appointment date/time, service/purpose, current status, and assigned doctor/admin name plus clinic contact phone only if the current client card normally presents them. Never expose staff-log wording, notification history, deciding actor, internal notes, notification IDs, price, or any other staff-only field; the client's own name/phone do not need to be repeated if the card already identifies the appointment.
- The client callback path is not a separate data model: it uses the same `AppointmentLogDetailsCB` / `AppointmentLogHideDetailsCB` payload shape and the same `appointment_log_details_kb` / `appointment_log_hide_details_kb` UI contract, but resolves against `get_appointment_for_client()` and the client-safe card renderer.
- A lost race edits the stale action message immediately to the same compact result that a passive recipient sees; it must not leave the old action buttons or a full card without `Скрыть`.
- Delete notifications remain terminal: retain their current alert/text and remove actions; do not provide details because the appointment row no longer exists.
- Callback data contains only the appointment ID; no patient name, phone, date, service, actor label, event text, or notification ID is exposed in Telegram callback data.
- Staff details must be denied when the appointment no longer exists or is outside the viewer's current clinic/doctor scope; client details must be denied when the appointment is missing, deleted, or not owned by the callback user.
- Preserve the distinction between `AppointmentAlreadyDecidedError` and `AppointmentAlreadyFinalizedError`.
- Do not stage, commit, or push without explicit user authorization.

---

### Task 1: Persist compact staff/client-log text and add the callback contracts

**Files:**
- Create: `bot/keyboards/admin/record_management_kb/appointment_log_details_cb.py`
- Create: `bot/keyboards/admin/record_management_kb/appointment_log_details_kb.py`
- Modify: `bot/models/appointment_notification.py`
- Modify: `bot/repositories/appointment_repository.py`
- Modify: `bot/services/appointment/appointment_management.py`
- Modify: `bot/handlers/utils/admin_utils/appointment_decision_helpers.py`
- Modify: `bot/handlers/admin/appointment_management/appointment_completion.py`
- Modify: `bot/handlers/client/appointment_response.py`
- Test: `tests/test_appointment_completion.py`
- Test: `tests/test_appointment_repository.py`
- Test: client appointment-response test module
- Test: repository fakes in affected service/handler test modules

**Interfaces:**
- `AppointmentLogDetailsCB(appointment_id: int)` and `AppointmentLogHideDetailsCB(appointment_id: int)` use distinct typed prefixes.
- `appointment_log_details_kb(appointment_id, lang)` and `appointment_log_hide_details_kb(appointment_id, lang)` return one localized button.
- `AppointmentNotification` gains nullable `compact_text`; legacy/action-only rows keep it `None`.
- `AppointmentRepository` adds a scoped lookup by `appointment_id`, `chat_id`, `message_id`, and expected notification kind, plus a method to set `compact_text` for an existing action prompt or a new `client_log` row.
- `staff_appointment_log_text(...)` renders a compact message once at delivery time; the stored result is the source of truth after `Скрыть`.
- `get_appointment_for_admin()` remains the authorization boundary for the staff callbacks.
- `get_appointment_for_client()` remains the authorization boundary for the client callbacks.
- The client callbacks reuse the shared `AppointmentLogDetailsCB` / `AppointmentLogHideDetailsCB` payload shape and the shared `appointment_log_details_kb` / `appointment_log_hide_details_kb` UI helpers. They require a stored `client_log` row matching the callback message plus ownership authorization; `Подробнее` edits that exact message to the client-safe full card and `Скрыть` restores its stored `compact_text`.

- [ ] Write failing repository tests for the nullable `compact_text` migration, save/update operations, and chat/message-scoped lookup; update every fake repository used by the new service contract.
- [ ] Run `python -m pytest -q tests/test_appointment_repository.py` and confirm the new cases fail before the schema and methods exist.
- [ ] Add portable `compact_text TEXT NULL` schema upgrade in `AppointmentRepository.init()`, map it in the domain model, and preserve all existing `kind` lookup behavior.
- [ ] Write failing handler tests for `Подробнее → Скрыть` on a completion result, including a missing compact-log row and an out-of-scope appointment.
- [ ] Replace completion-only details callbacks/keyboards with the generic contract; look up compact text from the callback message and preserve the exact delivered actor/outcome wording after hiding details.
- [ ] Write failing client handler tests for `Подробнее → Скрыть`: verify exact compact-text restoration, a missing/wrong-kind notification row, a deleted appointment, and a foreign appointment all fail closed without editing the message.
- [ ] Add the client handler and card renderer using `get_appointment_for_client()` plus the scoped `client_log` lookup; reuse the shared callback payload and keyboard helpers, but do not reuse the staff card renderer or staff authorization path.
- [ ] Keep client-facing coverage bounded to already-sent result or terminal notifications, with no change to client action prompts. The system currently sends no client completion notification after either manual completion or auto-completion, and this plan must not introduce one unless a later plan explicitly adds it.
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
- Test: client notification test modules affected by result senders

**Interfaces:**
- Result notification methods accept or derive the persisted `Appointment`, compact event kind, and deciding actor ID needed by the shared details renderer.
- `notify_staff_appointment_created`, staff booking decision notifications, staff reschedule decision notifications, client-proposal accepted/rejected logs, client cancellation/changed-time logs, and staff cancellation logs send the compact text with `appointment_log_details_kb`, then persist that exact text against the sent chat/message ID.
- Notification senders for unresolved booking/reschedule requests retain their existing action keyboards.
- Existing client result/terminal senders that do not attach operational controls send the existing compact event text with the shared `appointment_log_details_kb`, then persist that exact recipient-localized text in a `client_log` notification row against the returned chat/message ID. This covers only notifications for appointments that still exist; deleted-appointment alerts remain terminal and buttonless. Do not add a client completion notification in this task: neither manual completion nor auto-completion currently sends one.

- [ ] Add failing service tests that every non-deletion staff result sender attaches the shared details keyboard and persists the exact recipient-localized compact text.
- [ ] Add failing flow tests for admin/doctor creation, client booking confirmation/rejection, client reschedule decision, client proposed-time response, client cancellation, and staff cancellation fan-out.
- [ ] Update the senders and fan-out helpers to render compact event-specific text plus the shared keyboard, resolving the recipient language as they do today.
- [ ] Add failing client sender tests for each sent non-control result/terminal notification: the localized `Подробнее` keyboard is present and the exact sent text is persisted as `client_log`. Keep authorization/round-trip callback cases in Task 1.
- [ ] Attach the shared details keyboard contract to the applicable client result senders and persist each exact recipient-localized compact text after sending; retain the current invite, proposal, and confirmation/cancellation controls without adding a second details-only keyboard.
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
- [ ] Add explicit client checks that every eligible non-control notification has the compact → `Подробнее` → client-safe full card → `Скрыть` → exact original compact-text round trip, client action prompts stay operationally unchanged, and neither manual nor automatic completion sends a new client notification.
- [ ] Add a concrete QA example for the client card fields above so reviewers can confirm the expanded view shows only appointment ID text, clinic, date/time, service/purpose, current status, and the normally displayed doctor/admin or clinic contact fields, with no staff-only data.
- [ ] Run `python -m pytest -q` and `python -m ruff check` for every modified Python file, then `git diff --check`.
- [ ] Have a reviewer confirm no callback bypasses staff scope or client ownership checks, no action keyboard survives a resolved race, no client-facing operational prompt changed, client cards expose no staff-only data, and the client compact/details/hide scope stays limited to already-sent non-control result or terminal notifications.
