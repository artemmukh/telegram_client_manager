# Per-Doctor Pending Requests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a client submit one pending self-booking per doctor instead of one globally.

**Architecture:** Keep all business validation in `AppointmentManagement`. Resolve the selected staff member before checking pending requests, and filter the existing client appointment list by that doctor's ID. The handler must only start the wizard and list doctors; submission remains the authoritative validation point.

**Tech Stack:** Python, aiogram 3, pytest, pytest-asyncio, handwritten repository fakes.

## Global Constraints

- Do not modify database schema or repository SQL.
- Count only `CreatedBy.CLIENT` appointments whose status is `AppointmentStatus.PENDING` and whose `doctor_id` equals the selected doctor's ID; reject when that count is at least the explicit per-doctor cap of `1` in both bot instances.
- Do not count `CONFIRMED`, finalized, or admin-created appointments.
- Preserve the cancellation cooldown and slot-availability behavior.
- Keep handlers free of business rules; use the existing `PendingRequestLimitExceededError`.
- Do not touch unrelated user changes or push/merge to `master`.
- The service check remains a non-atomic read-count-write operation; do not expand this task into a database-concurrency redesign.

---

### Task 1: Scope pending self-booking validation to the selected doctor

**Files:**

- Modify: `bot/services/appointment/appointment_management.py:328-363,1042-1047`
- Modify: `bot/handlers/client/appointment_booking.py:47-55`
- Test: `tests/test_appointment_management.py:1193-1238`
- Test: `tests/test_appointment_booking_handler.py`
- Modify: `docs/superpowers/specs/2026-08-11-per-doctor-pending-requests-design.md`

**Interfaces:**

- Consumes: `AppointmentManagement.create_self_booking(client_telegram_id: int, data: dict) -> Appointment` and `Appointment.doctor_id: int`.
- Produces: `ensure_pending_limit_not_exceeded(client_telegram_id: int, doctor_id: int) -> None`, which rejects only an existing client-created pending request for that doctor.

- [ ] **Step 1: Write failing service tests**

Add two async tests using the local handwritten `FakeAppointmentRepository`:

```python
await service.ensure_pending_limit_not_exceeded(client.telegram_user_id, second_doctor.ID)

with pytest.raises(PendingRequestLimitExceededError):
    await service.ensure_pending_limit_not_exceeded(client.telegram_user_id, first_doctor.ID)
```

Seed the fake with a client-created `PENDING` appointment for `first_doctor`. The first assertion proves a different doctor is allowed; the second proves the same doctor remains blocked.
Update the existing finalized and admin-created limit tests to pass an explicit doctor ID, using the same ID for blocking cases and a distinct ID where the appointment must not count.

- [ ] **Step 2: Run the new service tests and verify RED**

Run:

```powershell
& 'C:\Users\user\PycharmProjects\PythonProject3\.venv\Scripts\python.exe' -m pytest -q tests\test_appointment_management.py -k "pending_limit"
```

Expected: FAIL because the current method has no `doctor_id` parameter and still counts every client-created pending request.

- [ ] **Step 3: Write failing handler test**

Add an async test for the booking router's `start_booking` behavior with a fake service whose `ensure_pending_limit_not_exceeded` raises if called. Invoke the `client_book_appointment` handler and assert that doctor selection is rendered rather than the exception being surfaced.

- [ ] **Step 4: Run the new handler test and verify RED**

Run:

```powershell
& 'C:\Users\user\PycharmProjects\PythonProject3\.venv\Scripts\python.exe' -m pytest -q tests\test_appointment_booking_handler.py -k "pending"
```

Expected: FAIL because `start_booking()` calls the global pending-limit guard before listing doctors.

- [ ] **Step 5: Implement the minimal service and handler change**

In `create_self_booking()`, resolve and validate `staff` before calling the limit method:

```python
staff = await self.user_repository.get_user_by_id(data["staff_user_id"])
if staff is None:
    raise UserNotFoundError(_STAFF_MEMBER_NOT_FOUND_MESSAGE)

await self.ensure_pending_limit_not_exceeded(client_telegram_id, staff.ID)
```

Add a module-level `MAX_PENDING_REQUESTS_PER_DOCTOR = 1`, remove the unused `MAX_PENDING_REQUESTS_PER_CLIENT` import, and change the helper signature and predicate:

```python
async def ensure_pending_limit_not_exceeded(self, client_telegram_id: int, doctor_id: int) -> None:
    pending_count = await self._count_pending_self_bookings(client_telegram_id, doctor_id)
    if pending_count >= MAX_PENDING_REQUESTS_PER_DOCTOR:
        raise PendingRequestLimitExceededError(_PENDING_REQUEST_LIMIT_MESSAGE)

if a.created_by == CreatedBy.CLIENT and a.status == AppointmentStatus.PENDING and a.doctor_id == doctor_id
```

Remove the pre-selection call from `start_booking()`. Do not change the existing exception, message, repository, database, cooldown, or slot code.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```powershell
& 'C:\Users\user\PycharmProjects\PythonProject3\.venv\Scripts\python.exe' -m pytest -q tests\test_appointment_management.py tests\test_appointment_booking_handler.py
```

Expected: PASS.

- [ ] **Step 7: Update the design document and commit the scoped change**

Record the exact tests added in the design document. Commit only the service, handler, tests, and the two design/plan documents on `codex/per-doctor-pending-limit`:

```powershell
git add bot/services/appointment/appointment_management.py bot/handlers/client/appointment_booking.py tests/test_appointment_management.py tests/test_appointment_booking_handler.py docs/superpowers/specs/2026-08-11-per-doctor-pending-requests-design.md docs/superpowers/plans/2026-08-11-per-doctor-pending-requests.md
git commit -m "feat: scope pending booking limit by doctor"
```

### Task 2: Verify the end-to-end self-booking behavior

**Files:**

- Modify: `tests/test_e2e_full_flow.py:394-425`
- Modify: `docs/superpowers/specs/2026-08-11-per-doctor-pending-requests-design.md`

**Interfaces:**

- Consumes: `AppointmentManagement.create_self_booking()` with `staff_user_id`.
- Produces: regression coverage for simultaneous pending requests to two distinct doctors.

- [ ] **Step 1: Write the failing end-to-end test**

Create a second doctor in the E2E fixture's clinic and submit two client-created requests from the same client to different doctor IDs. Assert both appointments are `PENDING`. Then submit a second request to the first doctor at a different available time and assert `PendingRequestLimitExceededError`.

- [ ] **Step 2: Run the new end-to-end test and verify GREEN**

Run:

```powershell
& 'C:\Users\user\PycharmProjects\PythonProject3\.venv\Scripts\python.exe' -m pytest -q tests\test_e2e_full_flow.py -k "pending"
```

Expected: PASS because Task 1 supplies the behavior. Seed the second doctor as an `ADMIN` user with one of the existing `zb` staff Telegram IDs (`226655040` or `37470594`), so it is a genuinely bookable clinic doctor.

- [ ] **Step 3: Update the design document and commit the regression coverage**

Add the E2E scenario to the testing section and commit only the test and design document:

```powershell
git add tests/test_e2e_full_flow.py docs/superpowers/specs/2026-08-11-per-doctor-pending-requests-design.md
git commit -m "test: cover pending requests for different doctors"
```

### Task 3: Run final validation

**Files:**

- Verify: `bot/services/appointment/appointment_management.py`
- Verify: `bot/handlers/client/appointment_booking.py`
- Verify: `tests/test_appointment_management.py`
- Verify: `tests/test_appointment_booking_handler.py`
- Verify: `tests/test_e2e_full_flow.py`

**Interfaces:**

- Consumes: completed Tasks 1 and 2.
- Produces: verification evidence for the scoped behavior.

- [ ] **Step 1: Run lint and whitespace validation**

Run:

```powershell
& 'C:\Users\user\PycharmProjects\PythonProject3\.venv\Scripts\python.exe' -m ruff check bot/services/appointment/appointment_management.py bot/handlers/client/appointment_booking.py tests/test_appointment_management.py tests/test_appointment_booking_handler.py tests/test_e2e_full_flow.py
git diff --check master...HEAD
```

Expected: PASS with no lint findings or whitespace errors.

- [ ] **Step 2: Run all affected tests**

Run:

```powershell
& 'C:\Users\user\PycharmProjects\PythonProject3\.venv\Scripts\python.exe' -m pytest -q tests/test_appointment_management.py tests/test_appointment_booking_handler.py tests/test_e2e_full_flow.py
```

Expected: PASS.

- [ ] **Step 3: Run the full suite**

Run:

```powershell
& 'C:\Users\user\PycharmProjects\PythonProject3\.venv\Scripts\python.exe' -m pytest -q
```

Expected: PASS.
