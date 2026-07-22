# Промпт: рефактор схемы БД (по фазам)

Это задание для агентов проекта. Исполнять строго по воркфлоу `CLAUDE.md`:
**planner → researcher → implementer → database-expert → test-expert → reviewer.**
`researcher` обязателен перед `implementer` — найти эталонную реализацию (см. ссылки в каждой фазе). Никогда не пропускать.

## Ведущий принцип

- `users` = идентичность/демография.
- `user_settings` = пользовательские настройки (durable-конфиг).
- Negotiation/transient-состояние живёт на родительской сущности (как `proposed_datetime` на `appointments`, `pending_full_name` на `users`).

## Общие правила и ограничения

- Стиль миграций проекта: схема в `init()` репозитория через `PRAGMA table_info` + защищённый `ALTER`. Эталоны: `staff_repository.init()` (backfill из users → drop колонки), `client_clinic_repository.init()` (backfill).
- Держать Postgres-портируемость: **никакого SQLite-only SQL** (`INSERT OR REPLACE`); upsert только через `INSERT ... ON CONFLICT(...) DO UPDATE`.
- Слои не смешивать: репозиторий не вызывает репозиторий (оркестрация — в сервисе); сервис не знает про Telegram; репозиторий не валидирует.
- **Бэкап `data/data_base.db` и `data/reminders.db` перед каждой деструктивной фазой** (2 и 3). Прецедент именования: `data_base.db.bak-before-drop-visibility-scope`.
- После каждой фазы — полный `pytest`. Каждая фаза самостоятельно поставляема и тестируема.
- Скиллы: `python-backend-guidelines` (рефактор/async), `repo-test-fakes` (тесты репозиториев), `sqlite-to-postgres-step` (портируемость).

## ⚠️ Сквозной риск №1 — позиционные индексы строк

`_row_to_user` и `_row_to_appointment` разбирают строку по индексам (`row[7]`, `row[9]`, ...). **Любое добавление/удаление/перенос колонки в `SELECT` сдвигает индексы** и молча ломает маппинг. В каждой фазе, меняющей `*_SELECT`, обязательно пересчитать ВСЕ индексы в соответствующем `_row_to_*` и в тесте проверить round-trip всех полей.
Рекомендация (опционально, отдельной задачей): перевести `_row_to_*` на доступ по имени (`aiosqlite.Row` / `row["col"]`), чтобы прекратить эту хрупкость. Не обязательно для этих фаз.

---

## ❓ Вопросы пользователю ДО реализации (задать через AskUserQuestion)

Эти решения по порядку колонок оставлены открытыми. Соответствующую фазу **не начинать**, пока пользователь не ответит.

- **Q1 (Фаза 1):** где разместить `gender` / `birth_date` в `users`?
  - (a) дописать в конец — простой `ALTER ADD`, без rebuild. *(дешевле, рекомендуется)*
  - (b) рядом с `full_name` (логическая группировка демографии) — требует rebuild таблицы `users`.
- **Q2 (Фаза 3):** в rebuild `appointments` заодно выкинуть мёртвую `admin_tg_id`? *(нигде не читается; рекомендуется да)*. Подтвердить, что 3 message_id-колонки в эту партию **не** входят (они уходят в отдельную фазу).
- **Q3 (Фаза 3):** подтвердить целевой порядок: `price` сразу после `purpose`.

Ответ на Q1 определяет, будет ли Фаза 1 простым `ALTER` или rebuild. Ответ на Q2 определяет состав колонок нового `appointments`.

---

## Фаза 1 — Добавить `gender` + `birth_date` в `users` (аддитивно, низкий риск)

**Цель:** демографические поля в `users`. Только схема + модель + чтение; функции ввода/редактирования — отдельной задачей позже.

**Зависит от:** Q1.

**Файлы:** `bot/models/user.py`, `bot/repositories/user_repository.py`, `tests/`.

**Шаги:**
1. Модель `User`: добавить `gender: str | None = None`, `birth_date: str | None = None`.
2. `user_repository.init()`: добавить колонки в `CREATE TABLE` (для свежих БД) + защищённый `ALTER ADD` для существующих (эталон — блок `pending_full_name`, стр. 65-68). Обе — `TEXT DEFAULT NULL`.
3. `USER_SELECT`: добавить `u.gender`, `u.birth_date`.
4. `_row_to_user`: обновить индексы (см. сквозной риск №1).

**Нюансы:**
- `birth_date` в ISO `'YYYY-MM-DD'` — по конвенции проекта (datetime как текст). Возраст не хранить (вычисляемый).
- `gender` — пермиссивный `TEXT` без `CHECK`. Валидация значений (`male`/`female`/...) и формата даты — в будущем валидаторе/сервисе, не в БД (правило CLAUDE.md).
- `create_user` не трогать — поля по умолчанию `NULL`.
- Если Q1 = (b), это уже rebuild `users` (см. процедуру в Фазе 3), а не `ALTER`.

**Риски:**
- Сдвиг позиционных индексов в `_row_to_user` → неверные значения полей. Митигируется round-trip тестом.
- Расхождение свежая vs мигрированная БД (`CREATE` содержит колонки, старой нужен `ALTER`) — обе ветки должны давать одинаковую схему. Тестировать обе.

**Тесты:** миграция старой БД добавляет колонки (`PRAGMA table_info`); вставка строки с `gender`/`birth_date` и чтение через `get_user_by_id` возвращает значения; существующие пользователи читаются с `gender=None` и всеми прочими полями корректно.

**Готово когда:** колонки есть на свежей и мигрированной БД, модель их несёт, весь `pytest` зелёный.

---

## Фаза 2 — Вынести настройки напоминаний в `user_settings` (средний риск)

**Цель:** убрать `reminder_24h` / `reminder_2h` из `users`, перенести в отдельную таблицу настроек. Поведение UI и джоб напоминаний — без изменений.

**Файлы:** новые `bot/models/user_settings.py`, `bot/repositories/user_settings_repository.py`; правки `bot/repositories/user_repository.py`, `bot/services/client/client_management.py`, `bot/run.py`; `tests/`.

**Целевая таблица:**
```sql
CREATE TABLE IF NOT EXISTS user_settings(
    user_id INTEGER PRIMARY KEY,
    reminder_24h INTEGER NOT NULL DEFAULT 1,
    reminder_2h  INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
)
```

**Шаги:**
1. Модель `UserSettings(user_id, reminder_24h, reminder_2h)`.
2. `UserSettingsRepository`: `init()`, `upsert(user_id, r24, r2)` (через `ON CONFLICT(user_id) DO UPDATE`), `get_by_user_id()`.
3. `init()` нового репозитория: create table → **под гардом `PRAGMA table_info(users)`**: backfill `INSERT OR IGNORE INTO user_settings(user_id, reminder_24h, reminder_2h) SELECT id, reminder_24h, reminder_2h FROM users` → `ALTER TABLE users DROP COLUMN reminder_24h` и `reminder_2h`. На свежей БД гард ложный — backfill/drop пропускаются.
4. `user_repository`: убрать reminder-колонки из `CREATE TABLE`; удалить два `ALTER`-гарда (стр. 55-63); в `USER_SELECT` заменить на `COALESCE(us.reminder_24h, 1)`, `COALESCE(us.reminder_2h, 1)` + `LEFT JOIN user_settings us ON us.user_id = u.id`; удалить метод `update_reminder_preferences` (стр. 230-233); обновить индексы `_row_to_user`.
5. `client_management`: в конструктор (стр. 23) добавить `user_settings_repository`; в `update_reminder_preferences` (стр. 221) заменить вызов на `self.user_settings_repository.upsert(...)`; строки `user.reminder_24h = ...` оставить.
6. `run.py`: создать `user_settings_repo = UserSettingsRepository(connection)`; `await user_settings_repo.init()` **после** `user_repo.init()` (стр. 58); прокинуть в `ClientManagement(...)`.

**Нюансы:**
- **Порядок init критичен:** `user_settings_repo.init()` после `user_repo.init()` (users должна существовать), и backfill обязан прочитать `users.reminder_*` ДО их drop → backfill и drop в одном init, под гардом наличия колонок.
- `COALESCE(...,1)` = у пользователей без строки настроек сохраняется дефолт «оба вкл»; строку при создании юзера можно не заводить.
- Upsert только `ON CONFLICT` (не `INSERT OR REPLACE` — SQLite-only и обнулит соседние поля).
- Репозиторий не зовёт репозиторий: запись настроек оркестрирует сервис.
- FK cascade: удаление юзера чистит настройки.
- Взаимодействие с Фазой 1: обе трогают `USER_SELECT`/`_row_to_user` — делать последовательно и перепроверять индексы после каждой.

**Риски:**
- Потеря данных, если drop выполнится до backfill или гард неверный → backfill+drop в одном init, под проверкой наличия колонок, тест на населённой БД.
- Двойной источник правды, если не все писатели переключены → `grep` подтвердить, что других писателей `reminder_*` не осталось.
- Изменение поведения джобы напоминаний → тест, что `appointment_jobs` читает флаги корректно после миграции.

**Тесты:** новый `test_user_settings_repository` (init/upsert/get); тест миграции (населённая `users` → настройки перенесены, колонки из `users` удалены); юзер без строки настроек читается с дефолтами; джоба напоминаний уважает настройки; сервис пишет в новый репозиторий.

**Готово когда:** в `users` нет reminder-колонок; `user_settings` держит их; поведение UI/джоб не изменилось; `pytest` зелёный.

---

## Фаза 3 — Перенести `price` после `datetime` в `appointments` (rebuild, высокий риск)

**Цель:** `price` сразу после `datetime`. Порядок колонок в SQLite — косметика (запросы по именам), поэтому это ради читаемости ценой полного rebuild таблицы.

**Зависит от:** Q2, Q3.

**Файлы:** `bot/repositories/appointment_repository.py`; при Q2=да также модель `Appointment`, `APPOINTMENT_SELECT`, `_row_to_appointment`; `tests/`.

**Целевой порядок (Q3):** `id, clinic_id, client_id, admin_id, datetime, purpose, price, created_by, status, created_at, status_updated_at, ...` (остальное без изменений; при Q2=да — без `admin_tg_id`).

**Шаги (каноническая процедура rebuild SQLite):**
1. Сохранить существующие `ALTER`-гарды (стр. 94-154) — они доводят очень старые БД до полного набора колонок ДО копирования.
2. `PRAGMA foreign_keys = OFF;` → `BEGIN;`
3. Создать `appointments_new` с целевым порядком колонок + все FK.
4. `INSERT INTO appointments_new (<явный список>) SELECT <тот же список> FROM appointments;`
5. `DROP TABLE appointments;` → `ALTER TABLE appointments_new RENAME TO appointments;`
6. Пересоздать индексы: `idx_appointments_clinic_datetime`, `idx_appointments_client`.
7. `PRAGMA foreign_key_check;` (должно быть пусто) → `COMMIT;` → `PRAGMA foreign_keys = ON;`
8. **Идемпотентность:** перед rebuild проверить текущий порядок через `PRAGMA table_info(appointments)`; если уже целевой — rebuild пропустить.

**Нюансы:**
- `appointment_notifications` имеет FK на `appointments(id) ON DELETE CASCADE`. Rebuild через rename сохраняет `id`, но FK-проверка обязательна (`foreign_key_check`).
- `init()` выполняется на каждом старте — без гарда идемпотентности rebuild будет прогоняться каждый запуск (риск + стоимость). Проверить, что второй `init()` — no-op.
- WAL активен — rebuild в транзакции корректен.
- При Q2=да: убрать `admin_tg_id` из нового `CREATE`, из `INSERT/SELECT`, из `APPOINTMENT_SELECT`, из модели и `_row_to_appointment` (синхронно, иначе чтения ломаются; сквозной риск №1).

**Риски:**
- **Наивысший риск фазы.** Потеря данных / порча FK при rebuild → обязателен бэкап + `foreign_key_check` + транзакция.
- Сирота `appointment_notifications`, если `id` изменится (не должен — копия сохраняет `id`) → проверить `foreign_key_check`.
- Rebuild на каждом старте при отсутствии гарда → тест идемпотентности.

**Тесты:** rebuild сохраняет все строки, значения и FK (`foreign_key_check` чист); порядок колонок целевой (`PRAGMA table_info`); повторный `init()` не пересобирает; связь `appointment_notifications` цела.

**Готово когда:** `price` после `datetime`; данные целы; индексы и FK целы; idempotent; `pytest` зелёный.

---

## Вне области (будущие фазы — не в этой партии)

- Дедупликация message_id (`notification_message_id`, `admin_notification_message_id`, `proposal_message_id`) → единая `appointment_notifications` (крупная фаза; убрать двойную запись, перевести чтения на таблицу). **⚠️  РИСК:** при удалении этих колонок через `ALTER TABLE ... DROP COLUMN` необходимо одновременно обновить `_TARGET_COLUMN_ORDER` и все CREATE/INSERT/SELECT списки в `_rebuild_appointments_if_column_order_stale()`, иначе rebuild будет срабатывать на каждом старте и краш при SELECT несуществующей колонки.
- `staff.visibility_scope` vs `is_doctor` — свести к одной колонке (обе кодируют одно).
- Вынести миграции из `init()` репозиториев в отдельный модуль перед миграцией на PostgreSQL.

## Финальная проверка (reviewer)

Прогнать чек-лист из `CLAUDE.md`: без дублей SQL/валидаторов/билдеров; SQL только в репозиториях; без Telegram в сервисах; слои целы; стиль сохранён; `pytest` зелёный.
