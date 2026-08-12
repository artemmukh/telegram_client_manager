# Completion Details and FSM Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a staff member's own successful appointment-completion notification compact and expandable, and prevent an older `Введите ФИ` input state from surviving that successful completion.

**Architecture:** Keep the completion follow-up independent from the inter-staff compact-notification feature. A small completion-specific callback pair switches the already-final `Приём завершён.` message between its compact text and the existing full appointment card. On either successful completion path, clear the prior chat FSM before retaining only the newly opened post-appointment card as the tracked screen.

**Tech Stack:** Python 3, aiogram 3, aiogram `CallbackData` and `FSMContext`, pytest, pytest-asyncio.

## Global Constraints

- Do not change status semantics: `AppointmentAlreadyDecidedError` remains a colleague-decision race and failed/finalized callbacks must keep their existing error handling.
- Do not clear FSM before `complete_appointment_by_admin()` succeeds.
- Keep the completion flow separate from the inter-staff `Подробнее / Скрыть` flow; do not add completion to staff-action event codes.
- The actor's compact message is exactly localized `Приём завершён.` / `Qabul yakunlandi.` and exposes localized `Подробнее / Batafsil`.
- The detail view is the existing `build_appointment_card()` output for an appointment visible to the acting staff member; it exposes localized `Скрыть / Yopish`.
- Callback data contains identifiers only, never client name, phone, service, or other card content.
- Record progress in `docs`; do not commit or push `master` without explicit user authorization.

---

## File Structure

- `bot/keyboards/admin/record_management_kb/completion_details_cb.py` — typed callback payloads for viewing and hiding details of the actor's own completed appointment.
- `bot/keyboards/admin/record_management_kb/completion_details_kb.py` — only builds the `Подробнее` and `Скрыть` keyboards.
- `bot/handlers/admin/appointment_management/appointment_completion.py` — attaches the compact keyboard after successful skip completion, clears obsolete FSM state after either successful completion, and handles the two detail callbacks.
- `tests/test_appointment_completion.py` — regression coverage for FSM reset and the compact/detail UI states.
- `docs/manual_qa_checklist.md` — manual Telegram regression steps for the formerly conflicting `Введите ФИ` sequence.

## Task 1: Add completion-detail callback and keyboard primitives

**Files:**
- Create: `bot/keyboards/admin/record_management_kb/completion_details_cb.py`
- Create: `bot/keyboards/admin/record_management_kb/completion_details_kb.py`
- Test: `tests/test_appointment_completion.py`

**Interfaces:**
- Produces: `CompletionDetailsCB(appointment_id: int)` and `CompletionHideDetailsCB(appointment_id: int)`.
- Produces: `completion_details_kb(appointment_id: int, lang: str = "ru") -> InlineKeyboardMarkup` and `completion_hide_details_kb(appointment_id: int, lang: str = "ru") -> InlineKeyboardMarkup`.

- [ ] **Step 1: Write failing keyboard/payload tests**

```python
def test_completion_details_keyboard_uses_only_appointment_id():
    markup = completion_details_kb(188, lang="ru")
    callback = CompletionDetailsCB.unpack(markup.inline_keyboard[0][0].callback_data)

    assert markup.inline_keyboard[0][0].text == "Подробнее"
    assert callback.appointment_id == 188
    assert callback.model_dump() == {"appointment_id": 188}
```

Add the symmetric Uzbek and hide-button assertions, including that hide uses `CompletionHideDetailsCB`.

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv\\Scripts\\python.exe -m pytest -q tests/test_appointment_completion.py -k "completion_details_keyboard"`

Expected: FAIL because the callback and keyboard modules do not yet exist.

- [ ] **Step 3: Implement the typed callbacks and keyboard-only builders**

```python
class CompletionDetailsCB(CallbackData, prefix="completion_details"):
    appointment_id: int


class CompletionHideDetailsCB(CallbackData, prefix="completion_hide_details"):
    appointment_id: int
```

Create one-button `InlineKeyboardBuilder` functions with labels `Подробнее` / `Batafsil` and `Скрыть` / `Yopish`; do not put authorization or appointment lookup logic in these modules.

- [ ] **Step 4: Run the focused keyboard tests**

Run: `.venv\\Scripts\\python.exe -m pytest -q tests/test_appointment_completion.py -k "completion_details_keyboard"`

Expected: PASS.

- [ ] **Step 5: Record the task result without committing**

Do not create a commit or push. Note the focused test result in the task handoff.

## Task 2: Clear obsolete FSM state after a successful completion

**Files:**
- Modify: `bot/handlers/admin/appointment_management/appointment_completion.py`
- Test: `tests/test_appointment_completion.py`

**Interfaces:**
- Consumes: `FSMContext.clear()` and existing `remember_tracked_message(state, message)`.
- Produces: after a successful `edit` completion, state data contains only the newly tracked appointment-card message; after successful `skip`, no stale state remains.

- [ ] **Step 1: Write failing FSM regression tests**

```python
@pytest.mark.asyncio
async def test_skip_completion_clears_an_active_name_search_state():
    state = MemoryStorage().get_context(bot=bot, chat_id=ADMIN_CHAT_ID, user_id=ADMIN_CHAT_ID)
    await state.set_state(AppointmentBrowserStates.search_name)
    await state.update_data(full_name="Черновик", card_message_id=111)

    await skip_handler(callback_query, CompletionFollowupCB(action="skip", appointment_id=1), state, admin)

    assert await state.get_state() is None
    assert await state.get_data() == {}
```

Add the `edit` variant: pre-load the same search state, invoke `open_edit`, then assert the state is `None` and its data contains the callback message's `card_chat_id` and `card_message_id`, but no `full_name`. Add failure-path tests proving `AppointmentAlreadyDecidedError` does not clear the pre-existing FSM.

- [ ] **Step 2: Run the new FSM tests to verify they fail**

Run: `.venv\\Scripts\\python.exe -m pytest -q tests/test_appointment_completion.py -k "clears_an_active_name_search_state or does_not_clear"`

Expected: FAIL because the current handlers leave the old search state intact.

- [ ] **Step 3: Apply the minimal handler change after successful domain completion only**

In `open_edit`, call `await state.clear()` after `complete_appointment_by_admin()` and scheduler resync have succeeded, then edit the callback message and call `remember_tracked_message()` as today. In `skip_edit`, accept `state: FSMContext` and call `await state.clear()` at the same successful point before editing the text.

Do not clear state in `AppointmentAlreadyDecidedError`, `BotException`, not-found, or notification-invalidation paths.

- [ ] **Step 4: Run the focused completion tests**

Run: `.venv\\Scripts\\python.exe -m pytest -q tests/test_appointment_completion.py`

Expected: PASS, including existing completion, race, scheduler-resync, and post-appointment-card tests.

- [ ] **Step 5: Record the task result without committing**

Do not create a commit or push. Keep the test output for the final review.

## Task 3: Add the actor-owned compact/detail completion UI

**Files:**
- Modify: `bot/handlers/admin/appointment_management/appointment_completion.py`
- Test: `tests/test_appointment_completion.py`

**Interfaces:**
- Consumes: `CompletionDetailsCB`, `CompletionHideDetailsCB`, `completion_details_kb()`, `completion_hide_details_kb()`, `build_appointment_card()`, and `AppointmentManagement.get_appointment_for_admin()`.
- Produces: the actor's successful `skip` message has `completion_details_kb`; details/hide callbacks edit that same message without creating a new Telegram message.

- [ ] **Step 1: Write failing handler tests for compact, details, hide, and authorization**

```python
@pytest.mark.asyncio
async def test_skip_completion_leaves_compact_message_with_details_button():
    await skip_handler(callback_query, CompletionFollowupCB(action="skip", appointment_id=1), state, admin)

    callback_query.message.edit_text.assert_called_once_with(
        "Приём завершён.", reply_markup=completion_details_kb(1, lang="ru"),
    )
```

Add tests that the details callback edits the same message to `build_appointment_card(appointment, "ru")` with the hide keyboard, hide restores compact text with the details keyboard, and a missing/out-of-scope appointment answers with an alert without editing the message.

- [ ] **Step 2: Run the new UI tests to verify they fail**

Run: `.venv\\Scripts\\python.exe -m pytest -q tests/test_appointment_completion.py -k "completion_details or skip_completion_leaves_compact"`

Expected: FAIL because no completion-details callbacks are registered and skip removes the keyboard.

- [ ] **Step 3: Implement UI handlers in the completion router**

Register `CompletionDetailsCB` and `CompletionHideDetailsCB` handlers in `create_admin_completion_router()`. Each handler must load the appointment via `get_appointment_for_admin(appointment_id, callback_query.from_user.id)`; on `None`, answer with the existing localized not-found alert and return without message edits.

For a visible appointment, acknowledge the callback and use `callback_query.message.edit_text()` to switch between:

```python
build_appointment_card(appointment, lang), reply_markup=completion_hide_details_kb(appointment.id, lang)
```

and:

```python
_APPOINTMENT_COMPLETED[lang], reply_markup=completion_details_kb(appointment.id, lang)
```

Change only the successful `skip_edit` final edit from `reply_markup=None` to `completion_details_kb(appointment.id, lang)`. Keep `open_edit` as the existing directly-open full editable card; it must not gain a redundant details button.

- [ ] **Step 4: Run all completion tests and lint the touched modules**

Run: `.venv\\Scripts\\python.exe -m pytest -q tests/test_appointment_completion.py; .venv\\Scripts\\python.exe -m ruff check bot/handlers/admin/appointment_management/appointment_completion.py bot/keyboards/admin/record_management_kb/completion_details_cb.py bot/keyboards/admin/record_management_kb/completion_details_kb.py tests/test_appointment_completion.py; git diff --check`

Expected: all commands succeed.

- [ ] **Step 5: Record the task result without committing**

Do not create a commit or push. The user has not authorized a master commit/push.

## Task 4: Document and manually verify the chat-level regression

**Files:**
- Modify: `docs/manual_qa_checklist.md`
- Test: `tests/test_appointment_completion.py`

**Interfaces:**
- Consumes: the final completion behavior from Tasks 2 and 3.
- Produces: a reproducible Telegram QA sequence confirming that no stale `Введите ФИ` operation remains after successful completion.

- [ ] **Step 1: Add a manual QA scenario**

Add a numbered scenario with these exact assertions:

1. Start appointment browsing and choose search by name until the bot displays `Введите ФИ:`.
2. Without sending a name, tap a valid completion follow-up's `Нет, всё верно`.
3. Confirm the follow-up is edited to `Приём завершён.` with `Подробнее`.
4. Send a valid full name; it must not continue the old appointment search.
5. Tap `Подробнее`, verify the full completed appointment card; tap `Скрыть`, verify the compact completion message returns.
6. Repeat with `Да, завершить`; verify the full post-appointment card opens and the old name search is not resumed.

- [ ] **Step 2: Run final targeted verification**

Run: `.venv\\Scripts\\python.exe -m pytest -q tests/test_appointment_completion.py; git diff --check`

Expected: PASS with no whitespace errors.

- [ ] **Step 3: Request review before any integration action**

Present changed files and verification output. Do not commit, push, or merge without explicit authorization.

## Plan Self-Review

- Coverage: Task 2 handles the stale global FSM root cause; Task 3 implements the actor-owned `Подробнее / Скрыть` UI; Task 1 establishes safe typed callback boundaries; Task 4 captures the exact Telegram regression.
- Scope: inter-staff compact notifications, client detail buttons, completion status rules, and `NO_SHOW` are explicitly excluded.
- Consistency: both completion action paths clear state only after a successful domain transition; only the `skip` path receives a compact final message because `edit` already opens the full appointment card.
