# План: видимость сотрудников и каналы уведомлений

Статус: бэклог. Ничего из перечисленного ниже не реализовано — это результат анализа,
а не одобренный план работ. Приоритеты — рекомендация, а не решение.

Все фазы идут через обязательный workflow проекта (`.claude/agents/workflow.md`):
planner → researcher → implementer → [aiogram-expert / database-expert при необходимости]
→ test-expert → routine → reviewer.

Контекст: сессия 2026-08-06, анализ того, как админ и врач видят действия друг друга,
как действия клиента попадают к ним в чат, и можно ли выбирать, за какими врачами следить.

---

## Что уже сделано (чтобы не переделывать)

В рамках той же сессии закрыт один пункт — «вечно живые кнопки у сотрудников»:

- `_CLOSED_REQUEST_TEXT` + `closed_request_text()` + `invalidate_closed_request_message()`
  в `bot/services/appointment/appointment_notifications.py`;
- гашение клавиатур при отмене клиентом — все три сайта в
  `bot/handlers/client/appointment_response.py`;
- гашение при истечении срока — `expire_pending_request_job` и
  `expire_reschedule_request_job` в `bot/services/appointment/appointment_jobs.py`;
- `tests/test_closed_request_invalidation.py`.

Отдельный шаблон заведён потому, что `_STALE_DECISION_TEXT` утверждает «{label} уже
принял(а) решение», а при отмене клиентом и при истечении срока решения сотрудника
не было вовсе.

---

## Тир 1 — сломанные сценарии

### 1.1 Продвижение сотрудника в staff не работает

Цепочка: `UserContextMiddleware` (`bot/middlewares/user.py:16`) читает строку из `users`;
админские роутеры закрыты `RoleFilter("admin")` → `get_user_role` → `SELECT role FROM users`;
`users.role` пишется **один раз** при регистрации из `auth.detect_role`
(`bot/handlers/registration.py:227`); повторно зарегистрироваться нельзя —
`register()` кидает `UserAlreadyExistsError` (`bot/services/utils/registration.py:132`),
а ветка `existing_user_id` роль не трогает.

Сценарий: человек зарегистрировался клиентом → позже его добавили в
`STAFF_SEED_BY_INSTANCE` → при рестарте `_seed_staff_by_clinic_token` создал строку в
`staff` → таблица `staff` говорит «сотрудник», `users.role` говорит `'client'` →
он навсегда видит клиентское меню. Чинится только руками:
`UPDATE users SET role='admin'`.

Два варианта, выбор за владельцем проекта:

- **дёшево:** `RoleFilter`/middleware перестаёт доверять `users.role` и спрашивает
  `staff` (там уже есть `AuthService.detect_role`); `users.role` становится кэшем;
- **дороже, чище:** синхронизация при старте — после сидинга `staff` подтянуть
  `users.role` для всех, кто есть в `staff`, но помечен клиентом.

Рекомендация: первый — источник истины становится один, ради чего таблицу `staff`
и заводили.

### 1.2 Свежая клиника не имеет ни одного получателя-администратора

`_seed_staff_by_clinic_token` (`bot/repositories/staff_repository.py`) вставляет только
`(telegram_user_id, clinic_id)` → `visibility_scope = NULL`.

`NULL` трактуется как `"own"` в фильтрах (`resolve_admin_appointment_filter`:
`in (None, "own")`), но исключается из веера (`resolve_notification_recipients`:
`!= "clinic"`). Итог: на новой клинике `resolve_notification_recipients` возвращает
только лечащего врача, пока кто-то не отредактирует БД.

Задача: проставлять явный `visibility_scope` при сидинге.

### 1.3 Нет write-path для `visibility_scope` / `is_doctor`

Единственные писатели этих колонок — миграционный backfill в
`StaffRepository.init()` (`bot/repositories/staff_repository.py:35-60`).
Ни хендлера, ни сервиса, ни админского UI. Любое изменение — руками в БД.

Связано с 1.1 и 1.2: пока пути записи нет, оба чинятся только вручную.

---

## Тир 2 — дефекты, которые окупаются при любом дальнейшем решении

### 2.1 `client_notifications.py` в обход единой точки веера

`bot/services/client/client_notifications.py:71,99` зовёт
`user_repository.get_staff_users_by_clinic_id(clinic_id)` напрямую, минуя
`resolve_notification_recipients`.

Проверено по всему репозиторию: это **единственный** обходной путь. Фоновые джобы
(`appointment_jobs.py:145,231,439`) и все staff-facing уведомления ходят через
`resolve_notification_recipients`.

Последствие сегодня: own-скоуп врач получает запросы на смену ФИ клиентов, которых
ему не показывают в браузере — канал уведомлений и канал просмотра расходятся.

Последствие завтра: `resolve_notification_recipients`
(`bot/services/appointment/appointment_management.py:1261`) — единственная точка
врезки для любой фильтрации подписок (см. 4.2). Оставленный обход означает, что
фича сразу поедет мимо.

Задача: направить оба вызова через `resolve_notification_recipients` или
эквивалентный scope-aware helper.

### 2.2 Fail-open дефолт в `list_clinic_doctors`

`bot/services/appointment/appointment_management.py:292`:
`is_doctor_by_telegram_id.get(u.telegram_user_id, True)`.

`staff.is_doctor` объявлен `NOT NULL DEFAULT 1`, значит дефолт `True` срабатывает
только для пользователя, которого в `staff` нет вообще. Пул кандидатов приходит из
`get_staff_users_by_clinic_id` (`bot/repositories/user_repository.py:198`), который
читает `users WHERE role='admin' AND clinic_id=?` и таблицу `staff` не трогает —
два запроса ключуются по разным колонкам (`users.clinic_id` против `staff.clinic_id`).

То есть дефолт — фолбэк ровно на случай расхождения, и он падает в открытую: такой
пользователь попадает в `list_bookable_staff` и становится доступен клиентам для записи.
Тестами это поведение не закреплено.

При одной клинике на БД расхождение маловероятно, но код его допускает.
Правка — однострочник (`False`).

### 2.3 `resolve_decision_label` игнорирует `is_doctor`

`bot/services/appointment/appointment_management.py:496-499` подписывает актора
«Администратор»/«Доктор» по `visibility_scope`, хотя для этого есть отдельное поле
`is_doctor`. Врач с clinic-скоупом подписан «Администратор» в чужих уведомлениях.
Косметика, правка на одну строку.

---

## Тир 3 — долг в канале уведомлений

### 3.1 `AppointmentAlreadyFinalizedError` не чистит сообщение актора

`invalidate_actor_stale_message` висит на `AppointmentAlreadyDecidedError`.
`AppointmentAlreadyFinalizedError` проваливается в общий `except BotException`
(`bot/handlers/admin/appointment_management/booking_requests.py:224`) — только popup,
клавиатура остаётся.

После сделанного (см. «Что уже сделано») бытовой путь сюда закрыт; остаётся настоящая
гонка — клиент отменил ровно в момент нажатия. Затрагивает 4+ хендлера, каждый требует
`try/except` вокруг `edit_text` (риск «message is not modified»), и в
`appointment_completion.py` семантика «финализирована» отличается от booking/reschedule.

### 3.2 В closed-request сообщении нет карточки записи

Обычная инвалидация (`invalidate_sibling_notifications`) добавляет карточку через
`build_appointment_card`. Новый путь — нет: `build_appointment_card` лежит в
`bot/handlers/utils/admin_utils/`, а импортировать его в клиентский хендлер и в
модуль джоб — пересечь слой.

Варианты: вынести построение карточки в сервисный слой, либо оставить как есть.

### 3.3 Клиентские хендлеры не записывают отправленные уведомления

`bot/handlers/client/appointment_response.py` — сайты отмены и accept/reject proposal
отправляют, но не зовут `record_notification`. При этом
`bot/handlers/client/appointment_reschedule.py:302` записывает.

Незаписанное сообщение не может быть якорем треда (`_admin_reply_to_message_id`)
и не может быть целью инвалидации.

### 3.4 `admin_notification_message_id` — легаси, который врёт

Колонка одна, чатов много. Сохраняется первый успешный send; комментарий в
`bot/handlers/client/appointment_booking.py:256-258` это признаёт, докстринг в
`bot/services/appointment/appointment_notifications.py:783-785` прямо говорит, что
колонка не может быть корректным якорем для обоих. Реально используется таблица
`appointment_notifications`; колонка — мёртвый вес, выглядящий как источник истины.

Задача: удалить колонку и её обновления, оставив только таблицу.

### 3.5 Удалённая запись теряет весь тред

`record=False` при `deleted=True` в `notify_staff_appointment_cancellation` —
потому что строку `appointments`, к которой относится FK, уже удалили.

### 3.6 Нет агрегации и тротлинга рассылок

Каждое действие клиента — N отдельных сообщений всем clinic-скоуп сотрудникам.
Ни дедупликации, ни сворачивания в ветку. При двух-трёх сотрудниках нормально,
при десяти админ получает поток.

---

## Тир 4 — редизайн

### 4.1 Разделить `visibility_scope` на две оси

Сейчас одна колонка означает две разные вещи:

| Ось | Кто читает |
|---|---|
| «что я вижу в браузере» | `resolve_admin_appointment_filter` → списки, календарь, карточки, блокировки, клиенты |
| «что мне шлют в личку» | `resolve_notification_recipients` → весь веер staff-уведомлений |

Пока это одно поле, невозможны обе естественные конфигурации: «вижу всю клинику,
но уведомления только по своим» и «слежу за врачами A и C, но не за B».

Побочно закрывает 1.2.

### 4.2 Фича: админ выбирает, за какими врачами следить

Сегодня такого нет вообще. Есть только транзиентный фильтр **вида**:

- `bot/handlers/admin/appointment_management/appointment_browser.py` —
  `maybe_prompt_doctor_filter` / `resolve_filtered_doctor_id` / `apply_doctor_filter`,
  хранится в FSM (`doctor_filter_id`, `calendar_doctor_filter_id`);
- `bot/keyboards/admin/record_management_kb/appointment_browser_kb.py:166-178` —
  single-select, не multi-select;
- на уведомления не влияет никак;
- FSM на `MemoryStorage` (`bot/create_bot.py:19`) — выбор теряется при каждом рестарте.

Хранилища подписок не существует: `user_settings` (`bot/repositories/user_settings_repository.py:11-19`)
знает только `reminder_24h`, `reminder_2h`, `language`.

Реализация — только после 4.1: подписка становится надстройкой над второй осью,
а точка врезки одна — `resolve_notification_recipients`. До 4.1 это отдельная
подсистема поверх поля, которое означает не то.

### 4.3 Один источник истины для «кто сотрудник»

`users.role = 'admin'` (снимок, сделанный один раз при регистрации) против таблицы
`staff` (сидится из `STAFF_SEED_BY_INSTANCE`). `RoleFilter` и
`get_staff_users_by_clinic_id` читают первое, вся scope-логика — второе.

Это корень 1.1 и 2.2. Если 1.1 делать «дёшево», 4.3 закрывается попутно.

---

## Не трогать

- `notify_client_appointment_changed` (`bot/services/appointment/appointment_notifications.py:758-774`)
  закомментирован **осознанно**, в коде стоит пометка «DISABLED INTENTIONALLY — do NOT restore».
  Прошлая сессия однажды ошибочно его «восстановила». Не включать без прямого указания.

---

## Рекомендуемый порядок

1. **1.1** — сломанный сценарий, а не долг.
2. **2.1** — окупается при любом решении по 4.2.
3. **2.2** — однострочник, убирает дыру в записи клиентов.
4. **2.3** — попутно.
5. **1.2 / 1.3** — вместе, они об одном.
6. **4.1** — только если 4.2 действительно нужна; иначе долг, который можно нести.

Тир 3 — по мере касания соответствующих файлов, отдельной фазой не стоит.
