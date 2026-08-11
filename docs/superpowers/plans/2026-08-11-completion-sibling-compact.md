# Completion Sibling Compact Notification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` for this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically replace a colleague's completion prompt with a compact completed-notification that names the deciding employee and retains that identity after opening and hiding details.

**Architecture:** Keep the completion CAS and notification lookup unchanged. Add typed callback data containing only `appointment_id` and persistent deciding `actor_user_id`; this lets the existing completion router rebuild the compact sibling message after `Скрыть` without storing a display name in callback data. The generic invalidation service gains optional pre-rendered text/markup, while all other decision notifications keep their current full-card/no-keyboard behavior.

**Tech Stack:** Python, aiogram 3, pytest, pytest-asyncio.

## Global Constraints

- A sibling completion notification is exactly a compact `Приём №N завершён.` plus `Завершил(а): <actor label>`, with `Подробнее`; expanded details use `Скрыть` and hiding restores the same actor-labelled compact message.
- Callback data carries integer identifiers only: `appointment_id` and `actor_user_id`; it never contains a staff name, client data, or phone.
- The acting employee's `skip` completion result remains the current `Приём завершён.` and existing details/hide controls; `edit` retains its current completed-card behavior.
- Resolve/attempt sibling edits immediately after successful completion and before scheduler resync, FSM clearing, callback answer, actor message edit, or tracking.
- Clear only the acting employee's FSM after a successful completion; keep lost-race and finalized exception branches separate.
- One sibling Telegram failure must not prevent attempts for the other stored sibling messages.
- No schema/repository change and no new notification is sent for an unrecorded original completion prompt.
- Do not stage, commit, or push without explicit user authorization.

---

### Task 1: Compact completion outcome for stored colleague prompts

**Files:**
- Create: `bot/keyboards/admin/record_management_kb/completion_sibling_details_cb.py`
- Create: `bot/keyboards/admin/record_management_kb/completion_sibling_details_kb.py`
- Modify: `bot/services/appointment/appointment_notifications.py`
- Modify: `bot/handlers/utils/admin_utils/appointment_decision_helpers.py`
- Modify: `bot/handlers/admin/appointment_management/appointment_completion.py`
- Modify: `tests/test_appointment_completion.py`

**Interfaces:**
- `CompletionSiblingDetailsCB(appointment_id: int, actor_user_id: int)` and `CompletionSiblingHideDetailsCB(...)` have unique typed prefixes.
- `completion_sibling_details_kb(appointment_id, actor_user_id, lang)` and `completion_sibling_hide_details_kb(...)` return one-button localized markup.
- `staff_completion_result_text(appointment_id, actor_label, lang)` returns the compact text.

- [ ] Write RED tests for compact sibling replacement, its Details/Hide round trip, and attempted sibling invalidation when actor `answer()` or `edit_text()` fails.
- [ ] Run `python -m pytest -q tests/test_appointment_completion.py` and confirm the new cases fail against current behavior.
- [ ] Implement the smallest typed callbacks/keyboards, compact renderer, per-target safe invalidation, and early sibling processing in both success branches.
- [ ] Run `python -m pytest -q tests/test_appointment_completion.py tests/test_appointment_decision_conflicts.py tests/test_staff_decision_notifications.py` and lint the modified files.
- [ ] Request a task review and a whole-diff review before reporting verification results.
