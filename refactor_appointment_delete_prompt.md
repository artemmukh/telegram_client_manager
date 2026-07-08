# Рефакторинг appointment_delete (удаление записей)

Взять `bot/handlers/admin/client_management/client_delete.py` как эталон и применить тот же принцип к `bot/handlers/admin/appointment_management/appointment_delete.py`.

## Текущее состояние

`appointment_delete.py` сразу запрашивает телефон (без меню, без поиска по ФИО, без подтверждения/редактирования введённых данных). После поиска сразу показывает записи с кнопкой «🗑 Удалить» на каждой (`show_appointments_with_actions` + `choose_appointment_to_delete_kb`), затем подтверждение (`appointment_delete_confirm_kb`).

Эта часть — «кнопки на каждой записи + подтверждение удаления» — уже реализована правильно и **не требует изменений**, её нужно только сохранить/переиспользовать.

## Что добавить (по аналогии с client_delete.py)

### 1. Клавиатуры

В `bot/keyboards/admin/record_management_kb/` (новый файл `appointment_deletion_kb.py` или дополнить `appointment_kb.py`):

- `appointment_deletion_kb()` — поиск по ФИО / по телефону / отмена (аналог `client_deletion_kb`)
- `appointment_search_to_delete_name_kb()` — подтвердить / изменить ФИО / отмена (аналог `client_search_to_delete_name_kb`)
- `appointment_search_to_delete_phone_kb()` — подтвердить / изменить номер / отмена (аналог `client_search_to_delete_phone_kb`)

### 2. Состояния

Расширить `AppointmentDeletionStates` в `appointment_states.py` до:

```
client_search_variant
client_search_name
client_search_phone
confirm_deletion
proceed
edit_full_name
edit_phone
```

(аналог `ClientDeletionStates`, `proceed` — уже существующее имя состояния, используемое текущими колбэками `appt_delete:` / `appt_approve_delete:`, сохранить как есть).

### 3. Хендлер

Переписать `appointment_delete.py`:

- `delete_record` → показать `appointment_deletion_kb()` вместо прямого запроса телефона
- поиск по ФИО: `ask_full_name` → `full_name_processing` → `show_confirmation` с `appointment_search_to_delete_name_kb()`
- поиск по телефону: `ask_phone` → `phone_processing` → `show_confirmation` с `appointment_search_to_delete_phone_kb()`
- редактирование ФИО/телефона на экране подтверждения: `edit_full_name` / `edit_phone` (как в `client_delete.py`)
- по подтверждению (`approve_appointment_delete`) — вызвать расширенный `appt_mng.search_appointments(data)` (принимает `dict` с `phone`/`full_name`, см. рефакторинг `appointment_search`) и вывести результат через уже существующие `show_appointments_with_actions(... , choose_appointment_to_delete_kb)`
- колбэки `appt_delete:` (выбор записи) и `appt_approve_delete:` (финальное подтверждение) оставить без изменений — переносить состояние в `proceed`, как сейчас

### 4. Сервис

Переиспользовать `AppointmentManagement.search_appointments`, расширенный под поиск по ФИО (`user_repository.get_clients_by_name` → записи всех найденных клиентов) в рамках рефакторинга `appointment_search`. Логику поиска не дублировать.

## Ограничения

- Следовать layered-архитектуре и workflow из `CLAUDE.md`: planner → researcher → implementer → aiogram-expert / sqlite-expert → reviewer.
- Не дублировать хелперы, валидаторы, клавиатуры — переиспользовать существующие из `client_management` и `appointment_helpers`.
- Handler не должен содержать бизнес-логику и SQL.
