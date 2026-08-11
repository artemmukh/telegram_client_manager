# Staff Role Source of Truth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the presence of a matching `staff` row the authoritative source for a registered user's current admin/client role.

**Architecture:** `AuthService` remains the single service that resolves staff membership. `RoleFilter` and `UserContextMiddleware` receive that service through aiogram dependency injection; both resolve from the registered user's clinic and staff row rather than the cached `users.role` value. The users table is not synchronized or backfilled in this change.

**Tech Stack:** Python 3, aiogram 3 dependency injection and middleware, aiosqlite repositories, pytest, pytest-asyncio.

## Global Constraints

- `staff` is authoritative only for users who already have a `users` row; a staff-only Telegram ID remains unregistered so it can complete registration.
- If a registered user has no matching `staff` row in their clinic, resolve to `Role.CLIENT` (fail closed for admin access).
- Do not add SQL to handlers, filters, or middleware; only `StaffRepository` continues to read `staff`.
- Do not alter the already-finished visibility/notification work or restore `notify_client_appointment_changed`.
- Do not commit or push without the user's explicit approval after each completed task.

---

## File Structure

- Modify `bot/services/utils/auth.py`: expose a user-based current-role resolver around existing `detect_role`.
- Modify `bot/utils/role.py`: have `RoleFilter` use the service instead of `UserRepository.get_user_role()`.
- Modify `bot/middlewares/user.py`: place a `User` carrying the authoritative role into `current_user`.
- Modify `bot/run.py`: construct `AuthService`, expose it to the dispatcher, and inject it into both user-context middleware registrations.
- Create `tests/test_authoritative_staff_roles.py`: focused service, filter, and middleware regressions with fakes.
- Modify `tests/test_admin_appointment_calendar_routing.py`: make its dispatcher fake comply with the new `auth_service` and middleware dependency contract.

### Task 1: Define and Test Authoritative Role Resolution

**Files:**
- Modify: `bot/services/utils/auth.py`
- Create: `tests/test_authoritative_staff_roles.py`

**Interfaces:**
- Consumes: `AuthService.detect_role(telegram_user_id: int, clinic_id: int) -> Role` and `User`.
- Produces: `AuthService.resolve_current_role(user: User | None) -> Role | None`; `None` means no registered user, while an existing user without staff resolves to `Role.CLIENT`.

- [x] **Step 1: Write failing service tests**

```python
@pytest.mark.asyncio
async def test_resolve_current_role_promotes_registered_client_in_staff():
    user = User(role=Role.CLIENT, telegram_user_id=10, clinic_id=1, full_name="U", phone="+998")
    auth = AuthService(FakeStaffRepository(Staff(telegram_user_id=10, clinic_id=1)))

    assert await auth.resolve_current_role(user) is Role.ADMIN


@pytest.mark.asyncio
async def test_resolve_current_role_is_fail_closed_when_staff_is_missing_or_other_clinic():
    user = User(role=Role.ADMIN, telegram_user_id=10, clinic_id=1, full_name="U", phone="+998")

    assert await AuthService(FakeStaffRepository(None)).resolve_current_role(user) is Role.CLIENT
    assert await AuthService(FakeStaffRepository(Staff(telegram_user_id=10, clinic_id=2))).resolve_current_role(user) is Role.CLIENT
```

- [x] **Step 2: Run the service tests to verify failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_authoritative_staff_roles.py -v`

Expected: FAIL because `AuthService.resolve_current_role` does not yet exist.

- [x] **Step 3: Add the minimal service method**

```python
async def resolve_current_role(self, user: User | None) -> Role | None:
    if user is None:
        return None
    return await self.detect_role(user.telegram_user_id, user.clinic_id)
```

Keep `detect_role` as the one place that asks `StaffRepository` whether the Telegram user belongs to the clinic. Handle invalid persisted users with missing `telegram_user_id` or `clinic_id` as `Role.CLIENT`, not as admin.

- [x] **Step 4: Run the service tests to verify success**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_authoritative_staff_roles.py -v`

Expected: PASS.

- [x] **Step 5: Stop for user review**

Report the changed files and the exact pytest result. Do not start Task 2 or commit until the user approves.

### Task 2: Route Filters and Current User Through the Resolver

**Files:**
- Modify: `bot/utils/role.py`
- Modify: `bot/middlewares/user.py`
- Modify: `bot/run.py`
- Modify: `tests/test_authoritative_staff_roles.py`
- Modify: `tests/test_admin_appointment_calendar_routing.py`

**Interfaces:**
- Consumes: `AuthService.resolve_current_role(user: User | None) -> Role | None` from Task 1.
- Produces: `RoleFilter.__call__(message, user_repo, auth_service) -> bool | dict` and `UserContextMiddleware(user_repo, auth_service)`.

- [x] **Step 1: Write failing filter and middleware regressions**

```python
@pytest.mark.asyncio
async def test_role_filter_allows_promoted_client_into_admin_router():
    result = await RoleFilter("admin")(message, user_repo, auth_service)
    assert result == {"role": Role.ADMIN}


@pytest.mark.asyncio
async def test_user_context_middleware_replaces_stale_cached_role():
    await middleware(handler, event, data)
    assert data["current_user"].role is Role.ADMIN


@pytest.mark.asyncio
async def test_role_filter_denies_cached_admin_without_matching_staff_row():
    assert await RoleFilter("admin")(message, user_repo, auth_service) is False
```

Cover the registered-user guest branch as well: a missing `User` must still only match `RoleFilter(None)`, regardless of a stray staff record.

- [x] **Step 2: Run the focused tests to verify failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_authoritative_staff_roles.py tests/test_admin_appointment_calendar_routing.py -v`

Expected: FAIL because the filter and middleware still depend on cached `users.role` and lack `auth_service`.

- [x] **Step 3: Implement the dependency-injected resolution path**

```python
# bot/run.py
auth_service = AuthService(staff_repo)
dp["auth_service"] = auth_service
dp.message.middleware(UserContextMiddleware(user_repo, auth_service))

# bot/middlewares/user.py
user = await self.user_repo.get_user_by_telegram_id(from_user.id)
if user is not None:
    data["current_user"] = replace(user, role=await self.auth_service.resolve_current_role(user))
```

In `RoleFilter`, obtain the `User` first. Use `RoleFilter(None)` only when it is absent; otherwise resolve through `auth_service` and return the `Role` enum value consistently with the existing `RoleFilter("admin")` comparisons. Update the dispatcher test fake to provide `dp["auth_service"]` and the new middleware constructor argument.

- [x] **Step 4: Run focused verification**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_authoritative_staff_roles.py tests/test_admin_appointment_calendar_routing.py tests/test_error_middleware.py -v`

Expected: PASS.

- [x] **Step 5: Stop for user review**

Report the exact changed files and results. Do not begin Task 3 or commit until the user approves.

### Task 3: Verify the Complete Role-Access Contract

**Files:**
- Modify: `bot/handlers/common/profile.py`
- Modify: `docs/planned_visibility_and_notifications.md`
- Modify: `tests/test_profile_handlers.py`
- Test: `tests/test_authoritative_staff_roles.py`
- Test: `tests/test_admin_appointment_calendar_routing.py`

**Interfaces:**
- Consumes: completed authoritative role resolution from Tasks 1 and 2.
- Produces: documented closure of backlog item 1.1 and full verification evidence.

- [x] **Step 1: Add the profile-language regression**

In `tests/test_profile_handlers.py`, pass an authoritative `current_user` with `Role.ADMIN` while `update_language()` returns a distinct persisted `User` with stale `Role.CLIENT`. Assert that the edited profile and bot commands remain admin after the language update. Run it first and confirm the stale-return behavior fails.

- [x] **Step 2: Preserve the authoritative request role while rerendering**

In `update_language_preset`, replace only the returned user's `role` with `current_user.role` before building the profile and selecting commands. Keep the returned language/settings, add no repository or SQL access to the handler, and leave `AuthService` as the source of role resolution.

- [x] **Step 3: Run the relevant role and routing suite**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_profile_handlers.py tests/test_authoritative_staff_roles.py tests/test_admin_appointment_calendar_routing.py tests/test_registration_service.py tests/test_registration_handlers.py tests/test_error_middleware.py -v`

Expected: PASS.

- [x] **Step 4: Run full validation**

Run: `.venv\\Scripts\\python.exe -m pytest -q`

Expected: PASS with no changed-test regressions.

- [x] **Step 5: Update the backlog document**

Mark only item 1.1 as completed and record that `staff` is the live source of access role for registered users, while `users.role` is retained only for stored compatibility. Record that the profile-language response retains the middleware-resolved role while applying returned language settings. Preserve the user's existing `.codex` workflow-link change.

- [ ] **Step 6: Stop for user review**

Give the full verification output summary and diff overview. Wait for explicit user approval before staging, committing, or proceeding further.
